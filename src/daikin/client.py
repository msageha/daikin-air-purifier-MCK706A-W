"""
DaikinClient: multireq による読み書きと、MCK706A 固有のアドレス・プロパティパス。

dgc_status 配下のプロパティの意味は公式 DAIKIN Smart App の空気清浄機向け定義
(GPFCjConvertValue) を一次情報とし、電源・運転切替・コース・風量・湿度設定は
実機 (MCK706A / FW 3_15_0) で書き込んで確認したもの。
"""

import math
from collections.abc import Sequence
from enum import StrEnum
from http import HTTPStatus
from typing import Any

import requests
from pydantic import ValidationError

from daikin.exceptions import DaikinConnectionError, DaikinError, DaikinUnsupportedError
from daikin.models import (
    AirStatus,
    Course,
    DecodedLeaf,
    DeviceInfo,
    FanSpeed,
    HumiditySetting,
    MultireqResponse,
)
from daikin.protocol import (
    RSC_SUCCESS,
    PropertyTree,
    build_read_requests,
    build_write_request,
    hex_to_ascii,
    hex_to_bool,
    hex_to_int,
    hex_to_temp,
    int_to_bool,
    int_to_hex,
    is_json_object,
)

# dgc_status が制御とセンサー、adp_i がアダプタ情報、adp_d がユーザー設定、
# adp_r が無線の接続状態、dev_i が機器種別。/dsiot/edge を読むと全アドレスを一括で列挙できる。
ADDR_STATUS = "/dsiot/edge/adr_0100.dgc_status"
ADDR_INFO = "/dsiot/edge.adp_i"
ADDR_DEVICE = "/dsiot/edge.adp_d"
ADDR_ADAPTER_RUNTIME = "/dsiot/edge.adp_r"
ADDR_DEVICE_TYPE = "/dsiot/edge.dev_i"

# dgc_status 配下のプロパティパス。
POWER_PATH = "e_1002/e_A002/p_01"
# 運転切替: 00 = 空気清浄、01 = 除湿 + 空気清浄 (MCK706A 非対応)、02 = 加湿 + 空気清浄。
HUMIDIFY_PATH = "e_1002/e_3001/p_3F"
# コースと手動風量は運転切替ごとに別プロパティに保存される (空気清浄側 / 加湿側)。
COURSE_PATHS = {False: "e_1002/e_3007/p_01", True: "e_1002/e_3007/p_03"}
FAN_SPEED_PATHS = {False: "e_1002/e_3007/p_04", True: "e_1002/e_3007/p_06"}
# 加湿運転時の湿度設定はコースごとに別プロパティ。smart / moist は自動なので本体に存在しない。
HUMIDITY_SETTING_PATHS = {
    Course.SMART: "e_1002/e_3007/p_12",
    Course.MANUAL: "e_1002/e_3007/p_13",
    Course.AUTO_FAN: "e_1002/e_3007/p_14",
    Course.ECONO: "e_1002/e_3007/p_15",
    Course.POLLEN: "e_1002/e_3007/p_16",
    Course.MOIST: "e_1002/e_3007/p_17",
    Course.CIRCULATOR: "e_1002/e_3007/p_18",
    Course.LAUNDRY_DRY: "e_1002/e_3007/p_19",
    Course.NIGHT_LAUNDRY_DRY: "e_1002/e_3007/p_1A",
    Course.WATER_DEODORIZE: "e_1002/e_3007/p_1B",
    Course.INTERNAL_DRY: "e_1002/e_3007/p_1C",
}
TEMPERATURE_PATH = "e_1002/e_A00B/p_01"
HUMIDITY_PATH = "e_1002/e_A00B/p_02"
PM25_LEVEL_PATH = "e_1002/e_3007/p_1D"
DUST_LEVEL_PATH = "e_1002/e_3007/p_1E"
ODOR_LEVEL_PATH = "e_1002/e_3007/p_1F"
PM25_RAW_PATH = "e_1002/e_3007/p_26"
DUST_RAW_PATH = "e_1002/e_3007/p_27"
ODOR_RAW_PATH = "e_1002/e_3007/p_28"
WATER_SUPPLY_SIGN_PATH = "e_1002/e_3007/p_20"
FILTER_DRYING_PATH = "e_1002/e_3007/p_29"
DEODORIZING_FILTER_OFF_SIGN_PATH = "e_1002/e_3007/p_3E"
STREAMER_MAINTENANCE_SIGN_PATH = "e_1002/e_3001/p_40"
ERROR_CODE_PATH = "e_1002/e_A004/p_09"

# 運転切替の wire 値 (1 バイト)。キーは加湿するか。
HUMIDIFY_CODES = {False: 0, True: 2}
# 列挙型プロパティの wire 値は enum の定義順 (0 始まり)。コースは 2 バイト、
# 風量と湿度設定は 1 バイト。
COURSE_CODES = {course: code for code, course in enumerate(Course)}
FAN_SPEED_CODES = {speed: code for code, speed in enumerate(FanSpeed)}
HUMIDITY_SETTING_CODES = {setting: code for code, setting in enumerate(HumiditySetting)}


class DaikinClient:
    """1 台の空気清浄機に対する同期クライアント。Session を共有するので並行利用はできない。"""

    def __init__(self, host: str, *, timeout: int = 10) -> None:
        self.host = host.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def _multireq(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        """
        /dsiot/multireq に本文を送り、responses 配列を返す。

        Raises:
            DaikinConnectionError: 本体へ到達できない。
            DaikinError: HTTP status が 2xx でない、または応答が multireq の形をしていない。
        """
        url = f"{self.host}/dsiot/multireq"
        try:
            resp = self._session.post(url, json=body, timeout=self._timeout)
        except requests.RequestException as err:
            raise DaikinConnectionError(
                f"Cannot reach Daikin unit at {self.host}: {err}"
            ) from err
        if not HTTPStatus.OK <= resp.status_code < HTTPStatus.MULTIPLE_CHOICES:
            raise DaikinError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
        # JSON の復号は、応答の encoding に従う requests に任せる (pydantic の JSON パーサーは UTF-8 だけを読む)。
        # 復号の失敗は requests.JSONDecodeError に限らず ValueError (桁数の上限を超える整数等) で届き、
        # ValidationError も ValueError の派生なので、ValueError で両方を受ける。
        try:
            payload = resp.json(
                parse_float=_parse_finite_float, parse_constant=_parse_finite_float
            )
            return MultireqResponse.model_validate(payload, strict=True).responses
        except ValueError as err:
            raise DaikinError(
                f"Unexpected dsiot response from {url}: {resp.text[:200]}"
            ) from err

    def read(self, targets: Sequence[str]) -> dict[str, dict[str, Any]]:
        """
        任意アドレスの生読み取り。応答を fr (応答元アドレス) で引ける dict にして返す。

        rsc は検査しない。エラー応答もそのまま観察できるようにするため。
        """
        by_address: dict[str, dict[str, Any]] = {}
        for resp in self._multireq(build_read_requests(targets)):
            fr = resp.get("fr", "")
            if not isinstance(fr, str):
                raise DaikinError(f"Unexpected fr in dsiot response: {fr!r}")
            by_address[fr] = resp
        return by_address

    def _read_trees(self, *targets: str) -> list[PropertyTree]:
        """targets を 1 回の multireq で読み、成功応答のプロパティツリーを targets の順で返す。"""
        by_address = self.read(targets)
        trees: list[PropertyTree] = []
        for target in targets:
            if (resp := by_address.get(target)) is None:
                raise DaikinError(f"No response for {target}")
            _raise_for_rsc(resp, what=f"Read of {target}")
            pc = resp.get("pc")
            if not is_json_object(pc):
                raise DaikinError(f"Response for {target} has no property tree")
            trees.append(PropertyTree(pc))
        return trees

    def write(self, to: str, *, entity_path: Sequence[str], pv: str) -> dict[str, Any]:
        """to のコンテナ配下で entity_path が指すリーフに pv (リトルエンディアン 16 進) を書く。"""
        responses = self._multireq(
            build_write_request(to, entity_path=entity_path, pv=pv)
        )
        if not responses:
            raise DaikinError(f"No response for write to {to}")
        _raise_for_rsc(responses[0], what=f"Write to {to} ({'/'.join(entity_path)})")
        return responses[0]

    def device_info(self) -> DeviceInfo:
        info, device, runtime, dev_type = self._read_trees(
            ADDR_INFO, ADDR_DEVICE, ADDR_ADAPTER_RUNTIME, ADDR_DEVICE_TYPE
        )
        try:
            return DeviceInfo.model_validate(
                {
                    "name": device.pv("name"),
                    "device_type": dev_type.pv("type"),
                    "mac": info.pv("mac"),
                    "firmware": info.pv("ver"),
                    "revision": info.pv("rev"),
                    "region": info.pv("reg"),
                    "ssid": info.pv("ssid"),
                    "wlan_ssid": runtime.pv("wlan_info/ssid"),
                    "wlan_rssi_dbm": runtime.pv("wlan_info/rssi"),
                    "api_ver": info.pv("api_ver"),
                    "led": device.decode("led", decoder=int_to_bool),
                    "timezone_offset_min": device.pv("timz/tmdf"),
                }
            )
        except ValidationError as err:
            raise DaikinError(f"Unexpected device info from unit: {err}") from err

    def air_status(self) -> AirStatus:
        status = self._read_trees(ADDR_STATUS)[0]
        humidify = status.decode(HUMIDIFY_PATH, decoder=_hex_to_humidify)
        humidify_course = status.decode(COURSE_PATHS[True], decoder=_hex_to_course)
        humidity_setting = None
        if humidify_course is not None:
            humidity_setting = status.decode(
                HUMIDITY_SETTING_PATHS[humidify_course],
                decoder=_hex_to_humidity_setting,
            )
        course = fan_speed = None
        if humidify is not None:
            course = status.decode(COURSE_PATHS[humidify], decoder=_hex_to_course)
            fan_speed = status.decode(
                FAN_SPEED_PATHS[humidify], decoder=_hex_to_fan_speed
            )
        return AirStatus(
            power=status.decode(POWER_PATH, decoder=hex_to_bool),
            humidify=humidify,
            course=course,
            fan_speed=fan_speed,
            humidity_setting=humidity_setting,
            temperature_c=status.decode(TEMPERATURE_PATH, decoder=hex_to_temp),
            humidity_pct=status.decode(HUMIDITY_PATH, decoder=hex_to_int),
            pm25_level=status.decode(PM25_LEVEL_PATH, decoder=hex_to_int),
            dust_level=status.decode(DUST_LEVEL_PATH, decoder=hex_to_int),
            odor_level=status.decode(ODOR_LEVEL_PATH, decoder=hex_to_int),
            pm25_raw=status.decode(PM25_RAW_PATH, decoder=hex_to_int),
            dust_raw=status.decode(DUST_RAW_PATH, decoder=hex_to_int),
            odor_raw=status.decode(ODOR_RAW_PATH, decoder=hex_to_int),
            water_supply_sign=status.decode(
                WATER_SUPPLY_SIGN_PATH, decoder=hex_to_bool
            ),
            filter_drying=status.decode(FILTER_DRYING_PATH, decoder=hex_to_bool),
            deodorizing_filter_off_sign=status.decode(
                DEODORIZING_FILTER_OFF_SIGN_PATH, decoder=hex_to_bool
            ),
            streamer_maintenance_sign=status.decode(
                STREAMER_MAINTENANCE_SIGN_PATH, decoder=hex_to_bool
            ),
            error_code=status.decode(ERROR_CODE_PATH, decoder=hex_to_ascii),
        )

    def status_tree(self) -> dict[str, DecodedLeaf]:
        """dgc_status の全リーフを復号して返す。未マップのプロパティを探すための入口。"""
        status = self._read_trees(ADDR_STATUS)[0]
        return {
            path: _decode_leaf(node, path=path) for path, node in status.leaves.items()
        }

    def set_power(self, *, on: bool) -> dict[str, Any]:
        return self.write(
            ADDR_STATUS, entity_path=POWER_PATH.split("/"), pv="01" if on else "00"
        )

    def set_humidify(self, *, on: bool) -> dict[str, Any]:
        """
        運転切替を加湿 + 空気清浄 (02) か空気清浄のみ (00) にする。

        Raises:
            DaikinUnsupportedError: 本体が加湿運転に対応しない。
        """
        status = self._read_trees(ADDR_STATUS)[0]
        code = HUMIDIFY_CODES[on]
        _require_supported(
            status,
            path=HUMIDIFY_PATH,
            code=code,
            what=f"humidify {'on' if on else 'off'}",
        )
        return self.write(
            ADDR_STATUS,
            entity_path=HUMIDIFY_PATH.split("/"),
            pv=int_to_hex(code, length=1),
        )

    def set_course(self, course: Course) -> dict[str, Any]:
        """
        現在の運転切替側のコースを変える。

        Raises:
            DaikinUnsupportedError: 現在の運転切替では選べないコース (空気清浄のみのときの moist 等)。
        """
        status = self._read_trees(ADDR_STATUS)[0]
        path = COURSE_PATHS[_current_humidify(status)]
        code = COURSE_CODES[course]
        _require_supported(status, path=path, code=code, what=f"course {course}")
        return self.write(
            ADDR_STATUS, entity_path=path.split("/"), pv=int_to_hex(code, length=2)
        )

    def set_fan_speed(self, speed: FanSpeed) -> dict[str, Any]:
        """
        現在の運転切替側の手動風量を変える。コースが manual でないと運転には反映されない。

        Raises:
            DaikinUnsupportedError: 本体が対応しない風量。
        """
        status = self._read_trees(ADDR_STATUS)[0]
        path = FAN_SPEED_PATHS[_current_humidify(status)]
        code = FAN_SPEED_CODES[speed]
        _require_supported(status, path=path, code=code, what=f"fan speed {speed}")
        return self.write(
            ADDR_STATUS, entity_path=path.split("/"), pv=int_to_hex(code, length=1)
        )

    def set_humidity_setting(self, setting: HumiditySetting) -> dict[str, Any]:
        """
        加湿側 (p_03) のコースに対する湿度設定を変える。humidify が false でも書ける。

        Raises:
            DaikinUnsupportedError: そのコースの湿度が自動 (smart / moist) か、本体が対応しない設定値。
        """
        status = self._read_trees(ADDR_STATUS)[0]
        course = status.decode(COURSE_PATHS[True], decoder=_hex_to_course)
        if course is None:
            raise DaikinError("Unit did not report the humidify-side course")
        path = HUMIDITY_SETTING_PATHS[course]
        if path not in status.leaves:
            raise DaikinUnsupportedError(
                f"humidity setting is automatic for course {course}"
            )
        code = HUMIDITY_SETTING_CODES[setting]
        _require_supported(
            status, path=path, code=code, what=f"humidity setting {setting}"
        )
        return self.write(
            ADDR_STATUS, entity_path=path.split("/"), pv=int_to_hex(code, length=1)
        )


def _parse_finite_float(text: str) -> float:
    """
    JSON の数値と NaN・Infinity の literal を float にし、有限でない値 (1e309 を含む) は ValueError にする。

    受け入れると、FastAPI が応答に直列化するときに null へ置き換わって不正な応答が 200 で返るか、int() で 500 になる。
    """
    if not math.isfinite(value := float(text)):
        raise ValueError(f"non-finite number {text} in JSON")
    return value


def _current_humidify(status: PropertyTree) -> bool:
    if (humidify := status.decode(HUMIDIFY_PATH, decoder=_hex_to_humidify)) is None:
        raise DaikinError("Unit did not report the operation changeover")
    return humidify


def _raise_for_rsc(resp: dict[str, Any], *, what: str) -> None:
    rsc = resp.get("rsc")
    if rsc is None:
        return
    # "2000" や true (bool は int の派生) を結果コードとして DaikinError.rsc (int) に載せないよう、JSON の整数以外は形の不正として扱う。
    if type(rsc) is not int:
        raise DaikinError(f"{what} returned a non-integer rsc: {rsc!r}")
    if rsc not in RSC_SUCCESS:
        raise DaikinError(f"{what} returned rsc={rsc}", rsc=rsc)


def _require_supported(tree: PropertyTree, *, path: str, code: int, what: str) -> None:
    """
    列挙型プロパティの md.mx (対応値のビットマスク) で code が選べるか確かめる。

    実機はビットマスク外の値も拒否せず保存してしまうので、書き込む前に弾く。
    """
    if (node := tree.leaves.get(path)) is None:
        raise DaikinError(f"Unit does not expose {path}")
    md = node.get("md")
    mask = md.get("mx") if is_json_object(md) else None
    if mask is None:
        raise DaikinError(f"Unit did not advertise supported values for {path}")
    try:
        supported = hex_to_int(mask)
    except (ValueError, TypeError) as err:
        raise DaikinError(f"Cannot decode {path} md.mx={mask!r}: {err}") from err
    if not (supported >> code) & 1:
        raise DaikinUnsupportedError(
            f"{what} is not supported by this unit (md.mx={mask})"
        )


def _hex_to_humidify(value: str) -> bool:
    code = hex_to_int(value)
    for humidify, humidify_code in HUMIDIFY_CODES.items():
        if humidify_code == code:
            return humidify
    raise ValueError(f"unsupported operation changeover {code}")


def _hex_to_course(value: str) -> Course:
    return _enum_from_code(Course, code=hex_to_int(value))


def _hex_to_fan_speed(value: str) -> FanSpeed:
    return _enum_from_code(FanSpeed, code=hex_to_int(value))


def _hex_to_humidity_setting(value: str) -> HumiditySetting:
    return _enum_from_code(HumiditySetting, code=hex_to_int(value))


def _enum_from_code[E: StrEnum](enum: type[E], *, code: int) -> E:
    members = list(enum)
    if not 0 <= code < len(members):
        raise ValueError(f"unknown {enum.__name__} code {code}")
    return members[code]


def _decode_leaf(node: dict[str, Any], *, path: str) -> DecodedLeaf:
    pv = node.get("pv")
    # md が null のリーフは、md が無いリーフと同じく、メタ情報の無いリーフとして返す。
    if (md := node.get("md")) is None:
        md = dict[str, Any]()
    if not is_json_object(md):
        raise DaikinError(f'"md" of {path} is not an object: {md!r}')
    value: Any = pv
    ascii_text = None
    if md.get("pt") == "b" and isinstance(pv, str) and pv:
        try:
            value = hex_to_int(pv)
            ascii_text = hex_to_ascii(pv)
        except ValueError:
            value = pv  # 16 進として読めない pv は生のまま返す
    return DecodedLeaf(
        pv=pv,
        value=value,
        type=md.get("pt"),
        min=md.get("mi"),
        max=md.get("mx"),
        ascii=ascii_text,
    )
