"""
MCK706A の dsiot の表現: アドレス・プロパティパス・wire 値の符号化と、プロパティツリーの組み立て。

値は README の「仕組み」「プロパティ対応表」「値の一覧」に従う。
"""

from collections.abc import Mapping
from typing import Any

STATUS = "/dsiot/edge/adr_0100.dgc_status"
ADAPTER_INFO = "/dsiot/edge.adp_i"
USER_SETTINGS = "/dsiot/edge.adp_d"
WIRELESS = "/dsiot/edge.adp_r"
DEVICE_TYPE = "/dsiot/edge.dev_i"

# wire 値の順 (0 始まり) に並べた、API が使う値。
COURSES = [
    "smart",
    "manual",
    "auto_fan",
    "econo",
    "pollen",
    "moist",
    "circulator",
    "laundry_dry",
    "night_laundry_dry",
    "water_deodorize",
    "internal_dry",
]
FAN_SPEEDS = ["quiet", "low", "standard", "high", "turbo"]
HUMIDITY_SETTINGS = ["off", "low", "standard", "high", "continuous"]
# 湿度が自動で、本体に湿度設定のプロパティが無いコース。
AUTOMATIC_HUMIDITY_COURSES = {"smart", "moist"}

POWER = "e_1002/e_A002/p_01"
# 00 = 空気清浄、02 = 加湿 + 空気清浄。キーは加湿するか。
HUMIDIFY = "e_1002/e_3001/p_3F"
HUMIDIFY_CODES = {False: 0, True: 2}
COURSE = {False: "e_1002/e_3007/p_01", True: "e_1002/e_3007/p_03"}
FAN_SPEED = {False: "e_1002/e_3007/p_04", True: "e_1002/e_3007/p_06"}
# 加湿側のコースごとの湿度設定。p_12 から コースの順に並ぶ。
HUMIDITY_SETTING = {
    course: f"e_1002/e_3007/p_{0x12 + code:02X}" for code, course in enumerate(COURSES)
}
TEMPERATURE = "e_1002/e_A00B/p_01"
HUMIDITY = "e_1002/e_A00B/p_02"
PM25_LEVEL = "e_1002/e_3007/p_1D"
DUST_LEVEL = "e_1002/e_3007/p_1E"
ODOR_LEVEL = "e_1002/e_3007/p_1F"
PM25_RAW = "e_1002/e_3007/p_26"
DUST_RAW = "e_1002/e_3007/p_27"
ODOR_RAW = "e_1002/e_3007/p_28"
WATER_SUPPLY_SIGN = "e_1002/e_3007/p_20"
FILTER_DRYING = "e_1002/e_3007/p_29"
DEODORIZING_FILTER_OFF_SIGN = "e_1002/e_3007/p_3E"
STREAMER_MAINTENANCE_SIGN = "e_1002/e_3001/p_40"
ERROR_CODE = "e_1002/e_A004/p_09"


_SENSORS = [
    TEMPERATURE,
    HUMIDITY,
    PM25_LEVEL,
    DUST_LEVEL,
    ODOR_LEVEL,
    PM25_RAW,
    DUST_RAW,
    ODOR_RAW,
    WATER_SUPPLY_SIGN,
    FILTER_DRYING,
    DEODORIZING_FILTER_OFF_SIGN,
    STREAMER_MAINTENANCE_SIGN,
    ERROR_CODE,
]


def le_hex(value: int, *, length: int, signed: bool = False) -> str:
    """値を length バイトのリトルエンディアン 16 進 (pv と md.mx の形式) にする。"""
    return value.to_bytes(length, "little", signed=signed).hex().upper()


def mask(codes: set[int], *, length: int) -> str:
    """選べる wire 値の集合を md.mx (bit n = 値 n のビットマスク) にする。"""
    return le_hex(sum(1 << code for code in codes), length=length)


def hex_leaf(pv: str, *, mx: str | None = None) -> dict[str, Any]:
    """`md.pt` が `b` (16 進バイト列) のリーフ。mx は列挙型の対応値のビットマスク。"""
    md: dict[str, Any] = {"pt": "b"}
    if mx is not None:
        md["mx"] = mx
    return {"pv": pv, "md": md}


def tree(name: str, *, leaves: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    """
    リーフのパス ("e_1002/e_A002/p_01") からリーフへの対応を、name を根とするプロパティツリー (pc) にする。

    リーフの pt は、リーフ自身が持たなければ 2。
    """
    root: dict[str, Any] = {"pn": name, "pt": 1, "pch": []}
    for path, leaf in leaves.items():
        node = root
        *containers, leaf_name = path.split("/")
        for container in containers:
            children: list[dict[str, Any]] = node["pch"]
            for child in children:
                if child["pn"] == container:
                    node = child
                    break
            else:
                new_child: dict[str, Any] = {"pn": container, "pt": 1, "pch": []}
                children.append(new_child)
                node = new_child
        node["pch"].append({"pn": leaf_name, "pt": 2, **leaf})
    return root


def mck706a_status() -> dict[str, dict[str, Any]]:
    """
    MCK706A の dgc_status のリーフ。README の取得例の状態 (空気清浄のみ・smart・quiet) を表す。

    対応範囲 (md.mx) は README の「値の一覧」の MCK706A: 空気清浄側のコースは moist を除く smart〜circulator、
    加湿側は smart〜circulator、風量は high 以外、湿度設定は low / standard / high。
    """
    purify_courses = {COURSES.index(c) for c in COURSES[:7] if c != "moist"}
    humidify_courses = set(range(7))
    fan_speeds = {FAN_SPEEDS.index(s) for s in FAN_SPEEDS if s != "high"}
    humidity_settings = {
        HUMIDITY_SETTINGS.index(s) for s in ("low", "standard", "high")
    }
    leaves = {
        POWER: hex_leaf("01"),
        HUMIDIFY: hex_leaf("00", mx=mask({0, 2}, length=1)),
        COURSE[False]: hex_leaf("0000", mx=mask(purify_courses, length=2)),
        COURSE[True]: hex_leaf("0000", mx=mask(humidify_courses, length=2)),
        FAN_SPEED[False]: hex_leaf("00", mx=mask(fan_speeds, length=1)),
        FAN_SPEED[True]: hex_leaf("00", mx=mask(fan_speeds, length=1)),
        TEMPERATURE: hex_leaf(le_hex(46, length=2)),
        HUMIDITY: hex_leaf(le_hex(73, length=1)),
        PM25_LEVEL: hex_leaf("00"),
        DUST_LEVEL: hex_leaf("00"),
        ODOR_LEVEL: hex_leaf("00"),
        PM25_RAW: hex_leaf(le_hex(659, length=3)),
        DUST_RAW: hex_leaf(le_hex(624, length=3)),
        ODOR_RAW: hex_leaf(le_hex(1018, length=3)),
        WATER_SUPPLY_SIGN: hex_leaf("00"),
        FILTER_DRYING: hex_leaf("00"),
        DEODORIZING_FILTER_OFF_SIGN: hex_leaf("00"),
        STREAMER_MAINTENANCE_SIGN: hex_leaf("00"),
        ERROR_CODE: hex_leaf(b"00-00\x00".hex().upper()),
    }
    for course in COURSES[:7]:
        if course not in AUTOMATIC_HUMIDITY_COURSES:
            leaves[HUMIDITY_SETTING[course]] = hex_leaf(
                "02", mx=mask(humidity_settings, length=1)
            )
    # 実機では設定値のリーフが pt 2、センサーと固定情報のリーフが pt 3。
    for path in _SENSORS:
        leaves[path]["pt"] = 3
    return leaves


def mck706a_containers() -> dict[str, dict[str, Any]]:
    """MCK706A が読み取りに返すアドレスごとのプロパティツリー。"""
    text = {"md": {"pt": "s"}}
    number = {"md": {"pt": "i"}}
    return {
        STATUS: tree("dgc_status", leaves=mck706a_status()),
        ADAPTER_INFO: tree(
            "adp_i",
            leaves={
                "mac": {"pv": "00005E005301", **text},
                "ver": {"pv": "3_15_0", **text},
                "rev": {"pv": "1A2B3C4", **text},
                "reg": {"pv": "jp", **text},
                "ssid": {"pv": "DaikinAP12345", **text},
                "api_ver": {"pv": "2_2", **text},
            },
        ),
        USER_SETTINGS: tree(
            "adp_d",
            leaves={
                "name": {"pv": "MCK706A", **text},
                "led": {"pv": 1, **number},
                "timz/tmdf": {"pv": 540, **number},
            },
        ),
        WIRELESS: tree(
            "adp_r",
            leaves={
                "wlan_info/ssid": {"pv": "home-network", **text},
                "wlan_info/rssi": {"pv": -46, **number},
            },
        ),
        DEVICE_TYPE: tree("dev_i", leaves={"type": {"pv": "1D", **text}}),
    }
