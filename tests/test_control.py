"""
POST /api/power・/api/humidify・/api/course・/api/fan-speed・/api/humidity-setting: 本体の設定を書き換える。

本体が対応しない値と、現在の運転状態では選べない値は、本体に送らずに 409 を返す。対応範囲は本体が
`md.mx` (bit n = 値 n のビットマスク) で申告するものを使う (README「値の一覧」)。
"""

from typing import Any

import pytest
import requests
from hypothesis import given, strategies as st

from tests import dsiot
from tests.dsiot import le_hex
from tests.harness import Stack, Write


def _set_status(stack: Stack, *, changes: dict[str, dict[str, Any] | None]) -> None:
    """MCK706A の dgc_status のリーフを changes で置き換える (None はリーフを消す)。"""
    leaves = dsiot.mck706a_status() | changes
    stack.unit.containers[dsiot.STATUS] = dsiot.tree(
        "dgc_status",
        leaves={path: leaf for path, leaf in leaves.items() if leaf is not None},
    )


def _humidify_leaf(*, on: bool) -> dict[str, Any]:
    return dsiot.hex_leaf(le_hex(dsiot.HUMIDIFY_CODES[on], length=1), mx="05")


def _bit(mask: int, *, code: int) -> bool:
    return bool(mask >> code & 1)


def _assert_written_or_409(
    stack: Stack,
    *,
    response: requests.Response,
    supported: bool,
    write: Write,
    body: dict[str, Any],
) -> None:
    if supported:
        assert response.status_code == 200
        assert response.json() == body
        assert stack.unit.writes == [write]
    else:
        assert response.status_code == 409
        assert stack.unit.writes == []


@pytest.mark.parametrize(("on", "pv"), [(True, "01"), (False, "00")])
def test_power_switches_the_unit_on_and_off(*, stack: Stack, on: bool, pv: str) -> None:
    stack.unit.reset()
    _set_status(stack, changes={dsiot.POWER: dsiot.hex_leaf("00" if on else "01")})

    response = stack.api.post("/api/power", json={"on": on})

    assert response.status_code == 200
    assert response.json() == {"power": on}
    assert stack.unit.writes == [Write(dsiot.STATUS, dsiot.POWER, pv)]
    assert stack.api.get("/api/status").json()["power"] is on


@given(on=st.booleans(), mask=st.integers(0, 0xFF))
def test_humidify_is_written_only_when_the_unit_supports_it(
    *, stack: Stack, on: bool, mask: int
) -> None:
    stack.unit.reset()
    _set_status(
        stack,
        changes={dsiot.HUMIDIFY: dsiot.hex_leaf("00", mx=le_hex(mask, length=1))},
    )
    code = dsiot.HUMIDIFY_CODES[on]

    response = stack.api.post("/api/humidify", json={"on": on})

    _assert_written_or_409(
        stack,
        response=response,
        supported=_bit(mask, code=code),
        write=Write(dsiot.STATUS, dsiot.HUMIDIFY, le_hex(code, length=1)),
        body={"humidify": on},
    )


@given(
    humidify=st.booleans(),
    course=st.sampled_from(dsiot.COURSES),
    mask=st.integers(0, 0xFFFF),
)
def test_course_is_written_to_the_current_changeover_side_when_supported(
    *, stack: Stack, humidify: bool, course: str, mask: int
) -> None:
    stack.unit.reset()
    path = dsiot.COURSE[humidify]
    _set_status(
        stack,
        changes={
            dsiot.HUMIDIFY: _humidify_leaf(on=humidify),
            path: dsiot.hex_leaf("0000", mx=le_hex(mask, length=2)),
        },
    )
    code = dsiot.COURSES.index(course)

    response = stack.api.post("/api/course", json={"course": course})

    _assert_written_or_409(
        stack,
        response=response,
        supported=_bit(mask, code=code),
        write=Write(dsiot.STATUS, path, le_hex(code, length=2)),
        body={"course": course},
    )


def test_moist_course_is_409_while_only_purifying(stack: Stack) -> None:
    """MCK706A の空気清浄側は moist (のど・はだ) を申告しない。"""
    stack.unit.reset()

    response = stack.api.post("/api/course", json={"course": "moist"})

    assert response.status_code == 409
    assert stack.unit.writes == []


@given(
    humidify=st.booleans(),
    speed=st.sampled_from(dsiot.FAN_SPEEDS),
    mask=st.integers(0, 0xFF),
)
def test_fan_speed_is_written_to_the_current_changeover_side_when_supported(
    *, stack: Stack, humidify: bool, speed: str, mask: int
) -> None:
    stack.unit.reset()
    path = dsiot.FAN_SPEED[humidify]
    _set_status(
        stack,
        changes={
            dsiot.HUMIDIFY: _humidify_leaf(on=humidify),
            path: dsiot.hex_leaf("00", mx=le_hex(mask, length=1)),
        },
    )
    code = dsiot.FAN_SPEEDS.index(speed)

    response = stack.api.post("/api/fan-speed", json={"fan_speed": speed})

    _assert_written_or_409(
        stack,
        response=response,
        supported=_bit(mask, code=code),
        write=Write(dsiot.STATUS, path, le_hex(code, length=1)),
        body={"fan_speed": speed},
    )


@given(
    humidify=st.booleans(),
    course=st.sampled_from(dsiot.COURSES),
    setting=st.sampled_from(dsiot.HUMIDITY_SETTINGS),
    mask=st.integers(0, 0xFF),
)
def test_humidity_setting_is_written_for_the_humidify_side_course_when_supported(
    *, stack: Stack, humidify: bool, course: str, setting: str, mask: int
) -> None:
    """湿度設定は運転切替によらず加湿側のコースに対するもので、smart / moist は自動なので 409。"""
    stack.unit.reset()
    changes: dict[str, dict[str, Any] | None] = {
        dsiot.HUMIDIFY: _humidify_leaf(on=humidify),
        dsiot.COURSE[True]: dsiot.hex_leaf(
            le_hex(dsiot.COURSES.index(course), length=2)
        ),
    }
    # ほかのコースは逆の範囲を申告し、別のコースの範囲で判定すると結果が変わるようにする。
    for each in dsiot.COURSES:
        if each not in dsiot.AUTOMATIC_HUMIDITY_COURSES:
            each_mask = mask if each == course else ~mask & 0xFF
            changes[dsiot.HUMIDITY_SETTING[each]] = dsiot.hex_leaf(
                "02", mx=le_hex(each_mask, length=1)
            )
    _set_status(stack, changes=changes)
    code = dsiot.HUMIDITY_SETTINGS.index(setting)

    response = stack.api.post(
        "/api/humidity-setting", json={"humidity_setting": setting}
    )

    _assert_written_or_409(
        stack,
        response=response,
        supported=course not in dsiot.AUTOMATIC_HUMIDITY_COURSES
        and _bit(mask, code=code),
        write=Write(
            dsiot.STATUS, dsiot.HUMIDITY_SETTING[course], le_hex(code, length=1)
        ),
        body={"humidity_setting": setting},
    )


_SETTERS = [
    ("/api/humidify", {"on": True}),
    ("/api/course", {"course": "manual"}),
    ("/api/fan-speed", {"fan_speed": "low"}),
    ("/api/humidity-setting", {"humidity_setting": "low"}),
]
_SETTER_IDS = ["humidify", "course", "fan-speed", "humidity-setting"]


@pytest.mark.parametrize(
    ("path", "body", "status"),
    [
        ("/api/humidify", {"on": True}, {"humidify": True}),
        ("/api/course", {"course": "manual"}, {"course": "manual"}),
        ("/api/fan-speed", {"fan_speed": "low"}, {"fan_speed": "low"}),
        (
            "/api/humidity-setting",
            {"humidity_setting": "low"},
            {"humidity_setting": "low"},
        ),
    ],
    ids=_SETTER_IDS,
)
def test_setting_is_read_back_by_status(
    *, stack: Stack, path: str, body: dict[str, Any], status: dict[str, Any]
) -> None:
    """書き込みの応答を受け取った後に読むと、書き込み後の状態が返る (README「値の一覧」の後の段落)。"""
    stack.unit.reset()
    # 湿度設定を書けるよう、加湿側のコースを manual にしておく。
    _set_status(stack, changes={dsiot.COURSE[True]: dsiot.hex_leaf("0100", mx="7F00")})

    assert stack.api.post(path, json=body).status_code == 200

    assert stack.api.get("/api/status").json().items() >= status.items()


_KNOWN_VALUES = {
    "/api/course": ("course", dsiot.COURSES),
    "/api/fan-speed": ("fan_speed", dsiot.FAN_SPEEDS),
    "/api/humidity-setting": ("humidity_setting", dsiot.HUMIDITY_SETTINGS),
}


@pytest.mark.parametrize("path", list(_KNOWN_VALUES))
@given(data=st.data())
def test_unknown_setting_value_is_rejected_without_contacting_the_unit(
    *, stack: Stack, path: str, data: st.DataObject
) -> None:
    field, known = _KNOWN_VALUES[path]
    value = data.draw(
        st.none() | st.integers() | st.text().filter(lambda v: v not in known)
    )
    stack.unit.reset()

    response = stack.api.post(path, json={field: value})

    assert response.status_code == 422
    assert stack.unit.received == 0


@pytest.mark.parametrize(
    ("path", "body", "missing"),
    [
        ("/api/course", {"course": "manual"}, dsiot.HUMIDIFY),
        ("/api/fan-speed", {"fan_speed": "low"}, dsiot.HUMIDIFY),
        ("/api/humidity-setting", {"humidity_setting": "low"}, dsiot.COURSE[True]),
        ("/api/humidify", {"on": True}, dsiot.HUMIDIFY),
    ],
    ids=[
        "course-without-changeover",
        "fan-speed-without-changeover",
        "humidity-setting-without-course",
        "humidify-without-property",
    ],
)
def test_setting_that_depends_on_an_unreported_property_is_502(
    *, stack: Stack, path: str, body: dict[str, Any], missing: str
) -> None:
    stack.unit.reset()
    _set_status(stack, changes={missing: None})

    response = stack.api.post(path, json=body)

    assert response.status_code == 502
    assert stack.unit.writes == []


@pytest.mark.parametrize("mx", [None, "zz"], ids=["missing", "not-hex"])
@pytest.mark.parametrize(("path", "body"), _SETTERS, ids=_SETTER_IDS)
def test_setting_without_a_readable_advertised_range_is_502(
    *, stack: Stack, path: str, body: dict[str, Any], mx: str | None
) -> None:
    """本体の md.mx を読めなければ、範囲外の値を送らないよう書き込まない。"""
    stack.unit.reset()
    leaves = dsiot.mck706a_status()
    for leaf in leaves.values():
        if mx is None:
            leaf["md"].pop("mx", None)
        elif "mx" in leaf["md"]:
            leaf["md"]["mx"] = mx
    leaves[dsiot.COURSE[True]] = dsiot.hex_leaf("0100")
    stack.unit.containers[dsiot.STATUS] = dsiot.tree("dgc_status", leaves=leaves)

    response = stack.api.post(path, json=body)

    assert response.status_code == 502
    assert stack.unit.writes == []


@pytest.mark.parametrize(
    ("path", "body"),
    [("/api/power", {"on": True}), *_SETTERS],
    ids=["power", *_SETTER_IDS],
)
def test_setting_rejected_by_the_unit_is_502_with_its_rsc(
    *, stack: Stack, path: str, body: dict[str, Any]
) -> None:
    stack.unit.reset()
    _set_status(stack, changes={dsiot.COURSE[True]: dsiot.hex_leaf("0100", mx="7F00")})
    stack.unit.write_rsc = 4000

    response = stack.api.post(path, json=body)

    assert response.status_code == 502
    assert response.json()["rsc"] == 4000
