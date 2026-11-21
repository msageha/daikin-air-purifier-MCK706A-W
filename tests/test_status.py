"""GET /api/status: dgc_status の運転状態とセンサー値を、README のプロパティ対応表どおりに復号して返す。"""

from typing import Any

import pytest
from hypothesis import example, given, strategies as st

from tests import dsiot
from tests.dsiot import le_hex
from tests.harness import Stack, as_json

# 値を持つ dgc_status のプロパティ: (パス, wire のバイト数, 生成する値)。
_UNSIGNED_FIELDS: dict[str, tuple[str, int, st.SearchStrategy[int]]] = {
    "humidity_pct": (dsiot.HUMIDITY, 1, st.integers(0, 100)),
    "pm25_level": (dsiot.PM25_LEVEL, 1, st.integers(0, 5)),
    "dust_level": (dsiot.DUST_LEVEL, 1, st.integers(0, 5)),
    "odor_level": (dsiot.ODOR_LEVEL, 1, st.integers(0, 5)),
    "pm25_raw": (dsiot.PM25_RAW, 3, st.integers(0, 2**24 - 1)),
    "dust_raw": (dsiot.DUST_RAW, 3, st.integers(0, 2**24 - 1)),
    "odor_raw": (dsiot.ODOR_RAW, 3, st.integers(0, 2**24 - 1)),
}
_FLAG_FIELDS = {
    "power": dsiot.POWER,
    "water_supply_sign": dsiot.WATER_SUPPLY_SIGN,
    "filter_drying": dsiot.FILTER_DRYING,
    "deodorizing_filter_off_sign": dsiot.DEODORIZING_FILTER_OFF_SIGN,
    "streamer_maintenance_sign": dsiot.STREAMER_MAINTENANCE_SIGN,
}
_HUMIDITY_SETTING_COURSES = [
    c for c in dsiot.COURSES if c not in dsiot.AUTOMATIC_HUMIDITY_COURSES
]


def _maybe[T](values: st.SearchStrategy[T]) -> st.SearchStrategy[T | None]:
    """値か、プロパティが本体に無いこと (None)。"""
    return st.none() | values


@st.composite
def _unit_states(draw: st.DrawFn) -> dict[str, Any]:
    """本体の状態 (API のフィールド名か、プロパティごとの値。None はプロパティが無い)。"""
    return {
        "humidify": draw(_maybe(st.booleans())),
        "course": {
            side: draw(_maybe(st.sampled_from(dsiot.COURSES))) for side in (False, True)
        },
        "fan_speed": {
            side: draw(_maybe(st.sampled_from(dsiot.FAN_SPEEDS)))
            for side in (False, True)
        },
        "humidity_settings": {
            course: draw(_maybe(st.sampled_from(dsiot.HUMIDITY_SETTINGS)))
            for course in _HUMIDITY_SETTING_COURSES
        },
        "temperature_half_c": draw(_maybe(st.integers(-(2**15), 2**15 - 1))),
        "error_code": draw(
            _maybe(st.from_regex(r"[0-9A-Z]{2}-[0-9]{2}", fullmatch=True))
        ),
        "flags": {name: draw(_maybe(st.booleans())) for name in _FLAG_FIELDS},
        "values": {
            name: draw(_maybe(values))
            for name, (_, _, values) in _UNSIGNED_FIELDS.items()
        },
    }


def _leaves(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """状態を README の符号化で dgc_status のリーフにする。"""
    pvs: dict[str, str | None] = {}
    humidify = state["humidify"]
    pvs[dsiot.HUMIDIFY] = (
        None if humidify is None else le_hex(dsiot.HUMIDIFY_CODES[humidify], length=1)
    )
    for side in (False, True):
        course = state["course"][side]
        pvs[dsiot.COURSE[side]] = (
            None if course is None else le_hex(dsiot.COURSES.index(course), length=2)
        )
        speed = state["fan_speed"][side]
        pvs[dsiot.FAN_SPEED[side]] = (
            None if speed is None else le_hex(dsiot.FAN_SPEEDS.index(speed), length=1)
        )
    for course, setting in state["humidity_settings"].items():
        pvs[dsiot.HUMIDITY_SETTING[course]] = (
            None
            if setting is None
            else le_hex(dsiot.HUMIDITY_SETTINGS.index(setting), length=1)
        )
    temperature = state["temperature_half_c"]
    pvs[dsiot.TEMPERATURE] = (
        None if temperature is None else le_hex(temperature, length=2, signed=True)
    )
    error_code = state["error_code"]
    # 固定長の領域に NUL 終端で入る。
    pvs[dsiot.ERROR_CODE] = (
        None if error_code is None else (error_code.encode() + b"\x00" * 3).hex()
    )
    for name, path in _FLAG_FIELDS.items():
        flag = state["flags"][name]
        pvs[path] = None if flag is None else le_hex(int(flag), length=1)
    for name, (path, length, _) in _UNSIGNED_FIELDS.items():
        value = state["values"][name]
        pvs[path] = None if value is None else le_hex(value, length=length)
    return {path: dsiot.hex_leaf(pv) for path, pv in pvs.items() if pv is not None}


def _expected(state: dict[str, Any]) -> dict[str, Any]:
    """README の対応表から導いた /api/status の応答。"""
    humidify = state["humidify"]
    humidify_course = state["course"][True]
    temperature = state["temperature_half_c"]
    return {
        "humidify": humidify,
        # course と fan_speed は現在の運転切替側の設定。運転切替が分からなければ決まらない。
        "course": None if humidify is None else state["course"][humidify],
        "fan_speed": None if humidify is None else state["fan_speed"][humidify],
        # 湿度設定は運転切替によらず加湿側のコースに対するもの。smart / moist は自動なので None。
        "humidity_setting": state["humidity_settings"].get(humidify_course),
        "temperature_c": None if temperature is None else temperature / 2,
        "error_code": state["error_code"],
        **state["flags"],
        **state["values"],
    }


@given(state=_unit_states())
@example(
    state={
        "humidify": True,
        "course": {False: "smart", True: "pollen"},
        "fan_speed": {False: "quiet", True: "turbo"},
        "humidity_settings": dict.fromkeys(_HUMIDITY_SETTING_COURSES, "high"),
        "temperature_half_c": -1,
        "error_code": "U4-01",
        "flags": dict.fromkeys(_FLAG_FIELDS, True),
        "values": dict.fromkeys(_UNSIGNED_FIELDS, 0),
    }
).via("加湿側の設定・氷点下の温度・すべてのサインが立った状態")
def test_status_decodes_unit_state(*, stack: Stack, state: dict[str, Any]) -> None:
    stack.unit.reset()
    stack.unit.containers[dsiot.STATUS] = dsiot.tree(
        "dgc_status", leaves=_leaves(state)
    )

    response = stack.api.get("/api/status")

    assert response.status_code == 200
    assert as_json(response.json()) == as_json(_expected(state))
    assert stack.unit.writes == []


def test_status_of_readme_example(stack: Stack) -> None:
    """README の「空気状態の取得例」の本体の状態は、その例と同じ応答になる。"""
    stack.unit.reset()

    response = stack.api.get("/api/status")

    assert response.status_code == 200
    assert as_json(response.json()) == as_json(
        {
            "power": True,
            "humidify": False,
            "course": "smart",
            "fan_speed": "quiet",
            "humidity_setting": None,
            "temperature_c": 23.0,
            "humidity_pct": 73,
            "pm25_level": 0,
            "dust_level": 0,
            "odor_level": 0,
            "pm25_raw": 659,
            "dust_raw": 624,
            "odor_raw": 1018,
            "water_supply_sign": False,
            "filter_drying": False,
            "deodorizing_filter_off_sign": False,
            "streamer_maintenance_sign": False,
            "error_code": "00-00",
        }
    )


def test_status_ignores_unmapped_properties(stack: Stack) -> None:
    """意味が未特定のプロパティは /api/status に含めない (README「プロパティ対応表」)。"""
    stack.unit.reset()
    expected = stack.api.get("/api/status").json()
    leaves = dsiot.mck706a_status() | {
        "e_1002/e_3007/p_2B": dsiot.hex_leaf("05"),
        "e_205E/p_01": {"pv": "anything", "md": {"pt": "s"}},
    }
    stack.unit.containers[dsiot.STATUS] = dsiot.tree("dgc_status", leaves=leaves)

    response = stack.api.get("/api/status")

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.parametrize(
    ("path", "pv"),
    [
        (dsiot.HUMIDIFY, "01"),
        (dsiot.COURSE[False], le_hex(11, length=2)),
        (dsiot.FAN_SPEED[False], le_hex(5, length=1)),
        (dsiot.HUMIDITY_SETTING["manual"], le_hex(5, length=1)),
        (dsiot.TEMPERATURE, "not hex"),
    ],
    ids=[
        "dehumidify-changeover",
        "course-code-11",
        "fan-speed-code-5",
        "humidity-setting-code-5",
        "non-hex-temperature",
    ],
)
def test_status_with_value_the_server_cannot_decode_is_502(
    *, stack: Stack, path: str, pv: str
) -> None:
    """範囲外の値が保存されていると 502 になる (README「エラー」)。"""
    stack.unit.reset()
    leaves = dsiot.mck706a_status()
    # 湿度設定は加湿側のコースのものだけを読むので、そのコースにしておく。
    leaves[dsiot.COURSE[True]] = dsiot.hex_leaf(le_hex(1, length=2))
    leaves[path] = dsiot.hex_leaf(pv)
    stack.unit.containers[dsiot.STATUS] = dsiot.tree("dgc_status", leaves=leaves)

    response = stack.api.get("/api/status")

    assert response.status_code == 502
