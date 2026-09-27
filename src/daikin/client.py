"""DaikinClient: multireq による読み書きと、MCK706A 固有のアドレス・プロパティパス。"""

from collections.abc import Sequence
from typing import Any

import requests
from pydantic import ValidationError

from .exceptions import DaikinConnectionError, DaikinError
from .models import AirStatus, DecodedLeaf, DeviceInfo
from .protocol import (
    RSC_OK,
    PropertyTree,
    build_read_requests,
    build_write_request,
    hex_to_ascii,
    hex_to_bool,
    hex_to_int,
    hex_to_temp,
    int_to_bool,
)

# dgc_status が制御とセンサー、adp_i がアダプタ情報、adp_d がユーザー設定。
ADDR_STATUS = "/dsiot/edge/adr_0100.dgc_status"
ADDR_INFO = "/dsiot/edge.adp_i"
ADDR_DEVICE = "/dsiot/edge.adp_d"

# dgc_status 配下のプロパティパス。実機 (FW 3_15_0) の解析結果で、
# power / temperature / humidity 以外の意味は暫定。
POWER_PATH = "e_1002/e_A002/p_01"
TEMPERATURE_PATH = "e_1002/e_A00B/p_01"
HUMIDITY_PATH = "e_1002/e_A00B/p_02"
MODE_PATH = "e_1002/e_3001/p_3F"
FAN_RATE_PATH = "e_1002/e_3007/p_32"
MONITOR_PATHS = {
    "monitor_a": "e_1002/e_3007/p_3A",
    "monitor_b": "e_1002/e_3007/p_3B",
    "pm_a": "e_1002/e_205E/p_01",
    "pm_b": "e_1002/e_205E/p_02",
}


class DaikinClient:
    """1 台の空気清浄機に対する同期クライアント。Session を共有するので並行利用はできない。"""

    def __init__(self, host: str, *, timeout: int = 10) -> None:
        self.host = host.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def _multireq(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        """/dsiot/multireq に本文を送り、responses 配列を返す。

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
        if not 200 <= resp.status_code < 300:
            raise DaikinError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
        try:
            payload = resp.json()
        except ValueError as err:
            raise DaikinError(
                f"Non-JSON response from {url}: {resp.text[:200]}"
            ) from err
        responses = payload.get("responses") if isinstance(payload, dict) else None
        is_multireq = isinstance(responses, list) and all(
            isinstance(r, dict) for r in responses
        )
        if not is_multireq:
            raise DaikinError(f"Unexpected dsiot response: {payload!r}")
        return responses

    def read(self, targets: Sequence[str]) -> dict[str, dict[str, Any]]:
        """任意アドレスの生読み取り。応答を fr (応答元アドレス) で引ける dict にして返す。

        rsc は検査しない。エラー応答もそのまま観察できるようにするため。
        """
        responses = self._multireq(build_read_requests(targets))
        return {r.get("fr", ""): r for r in responses}

    def _read_trees(self, *targets: str) -> list[PropertyTree]:
        """targets を 1 回の multireq で読み、成功応答のプロパティツリーを targets の順で返す。"""
        by_address = self.read(targets)
        trees = []
        for target in targets:
            resp = by_address.get(target)
            if resp is None:
                raise DaikinError(f"No response for {target}")
            _raise_for_rsc(resp, f"Read of {target}")
            pc = resp.get("pc")
            if not isinstance(pc, dict):
                raise DaikinError(f"Response for {target} has no property tree")
            trees.append(PropertyTree(pc))
        return trees

    def write(self, to: str, entity_path: Sequence[str], pv: str) -> dict[str, Any]:
        """to のコンテナ配下で entity_path が指すリーフに pv (リトルエンディアン 16 進) を書く。"""
        responses = self._multireq(build_write_request(to, entity_path, pv))
        if not responses:
            raise DaikinError(f"No response for write to {to}")
        _raise_for_rsc(responses[0], f"Write to {to} ({'/'.join(entity_path)})")
        return responses[0]

    def device_info(self) -> DeviceInfo:
        info, device = self._read_trees(ADDR_INFO, ADDR_DEVICE)
        try:
            return DeviceInfo(
                name=device.pv("name"),
                mac=info.pv("mac"),
                firmware=info.pv("ver"),
                revision=info.pv("rev"),
                region=info.pv("reg"),
                ssid=info.pv("ssid"),
                api_ver=info.pv("api_ver"),
                led=device.decode("led", int_to_bool),
                timezone_offset_min=device.pv("timz/tmdf"),
            )
        except ValidationError as err:
            raise DaikinError(f"Unexpected device info from unit: {err}") from err

    def air_status(self) -> AirStatus:
        status = self._read_trees(ADDR_STATUS)[0]
        return AirStatus(
            power=status.decode(POWER_PATH, hex_to_bool),
            temperature_c=status.decode(TEMPERATURE_PATH, hex_to_temp),
            humidity_pct=status.decode(HUMIDITY_PATH, hex_to_int),
            mode=status.decode(MODE_PATH, hex_to_int),
            fan_rate=status.decode(FAN_RATE_PATH, hex_to_int),
            monitors={
                name: status.decode(path, hex_to_int)
                for name, path in MONITOR_PATHS.items()
            },
        )

    def status_tree(self) -> dict[str, DecodedLeaf]:
        """dgc_status の全リーフを復号して返す。未マップのプロパティを探すための入口。"""
        status = self._read_trees(ADDR_STATUS)[0]
        return {path: _decode_leaf(node) for path, node in status.leaves.items()}

    def set_power(self, on: bool) -> dict[str, Any]:
        return self.write(ADDR_STATUS, POWER_PATH.split("/"), "01" if on else "00")


def _raise_for_rsc(resp: dict[str, Any], what: str) -> None:
    rsc = resp.get("rsc")
    if rsc not in (None, RSC_OK):
        raise DaikinError(f"{what} returned rsc={rsc}", rsc=rsc)


def _decode_leaf(node: dict[str, Any]) -> DecodedLeaf:
    pv = node.get("pv")
    md = node.get("md") or {}
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
