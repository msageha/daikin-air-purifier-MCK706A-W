"""本体と通信する全 endpoint の失敗時の status: 到達できなければ 504、応答を解釈できなければ 502 (README「エラー」)。"""

import pytest

from tests import dsiot
from tests.harness import HttpReply, Stack

_ENDPOINTS: list[tuple[str, str, object]] = [
    ("GET", "/api/status", None),
    ("GET", "/api/info", None),
    ("GET", "/api/tree", None),
    ("POST", "/api/read", {"targets": [dsiot.STATUS]}),
    (
        "POST",
        "/api/write",
        {
            "to": dsiot.STATUS,
            "entity_path": ["e_1002", "e_A002", "p_01"],
            "pv": "00",
            "confirm": True,
        },
    ),
    ("POST", "/api/power", {"on": False}),
    ("POST", "/api/humidify", {"on": True}),
    ("POST", "/api/course", {"course": "manual"}),
    ("POST", "/api/fan-speed", {"fan_speed": "low"}),
    ("POST", "/api/humidity-setting", {"humidity_setting": "low"}),
]
_endpoints = pytest.mark.parametrize(
    ("method", "path", "body"), _ENDPOINTS, ids=[path for _, path, _ in _ENDPOINTS]
)


@_endpoints
def test_unreachable_unit_is_504(
    *, stack: Stack, method: str, path: str, body: object
) -> None:
    stack.unit.reset()
    stack.unit.reachable = False

    response = stack.api.request(method, path=path, json=body)

    assert response.status_code == 504


@pytest.mark.parametrize(
    "reply",
    [
        HttpReply(500, "text/plain", b"internal error"),
        HttpReply(404, "text/html", b"<html>not found</html>"),
        HttpReply(200, "text/html", b"<html>not json</html>"),
        HttpReply.json({"result": []}),
        HttpReply.json({"responses": {"fr": dsiot.STATUS}}),
        HttpReply.json({"responses": ["not an object"]}),
        HttpReply(
            200,
            "application/json",
            b'{"responses": [{"fr": "/dsiot/edge", "rsc": NaN}]}',
        ),
        HttpReply(
            200,
            "application/json",
            b'{"responses": [{"fr": "/dsiot/edge", "rsc": 1e999}]}',
        ),
    ],
    ids=[
        "http-500",
        "http-404",
        "not-json",
        "no-responses",
        "responses-not-list",
        "response-not-object",
        "nan",
        "infinity",
    ],
)
@_endpoints
def test_uninterpretable_reply_is_502(
    *, stack: Stack, method: str, path: str, body: object, reply: HttpReply
) -> None:
    stack.unit.reset()
    stack.unit.reply = reply

    response = stack.api.request(method, path=path, json=body)

    assert response.status_code == 502
    assert response.json().keys() == {"detail", "rsc"}


_READS_STATUS_FIRST = [
    e
    for e in _ENDPOINTS
    if e[1]
    in {
        "/api/status",
        "/api/tree",
        "/api/humidify",
        "/api/course",
        "/api/fan-speed",
        "/api/humidity-setting",
    }
]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    _READS_STATUS_FIRST,
    ids=[path for _, path, _ in _READS_STATUS_FIRST],
)
def test_failed_read_of_the_status_is_502_with_its_rsc(
    *, stack: Stack, method: str, path: str, body: object
) -> None:
    """dgc_status の読み取りに本体が失敗の rsc を返すと 502 で、操作は書き込まない。"""
    stack.unit.reset()
    stack.unit.read_rsc[dsiot.STATUS] = 4000

    response = stack.api.request(method, path=path, json=body)

    assert response.status_code == 502
    assert response.json()["rsc"] == 4000
    assert stack.unit.writes == []


_NON_INTEGER_RSC = pytest.mark.parametrize(
    "rsc",
    [{"rsc": "2000"}, {"rsc": True}, {"rsc": None}, {}],
    ids=["string", "bool", "null", "missing"],
)


@_NON_INTEGER_RSC
def test_status_read_without_an_integer_result_code_is_502(
    *, stack: Stack, rsc: dict[str, object]
) -> None:
    """rsc が整数でなければ、プロパティツリーがあっても成功とみなさない。"""
    stack.unit.reset()
    pc = stack.unit.containers[dsiot.STATUS]
    stack.unit.reply = HttpReply.json(
        {"responses": [{"fr": dsiot.STATUS, "pc": pc, **rsc}]}
    )

    response = stack.api.get("/api/status")

    assert response.status_code == 502


@_NON_INTEGER_RSC
def test_write_without_an_integer_result_code_is_502(
    *, stack: Stack, rsc: dict[str, object]
) -> None:
    """本体が書き込みの成功を報告しなければ、成功として返さない。"""
    stack.unit.reset()
    stack.unit.reply = HttpReply.json({"responses": [{"fr": dsiot.STATUS, **rsc}]})

    response = stack.api.post("/api/power", json={"on": False})

    assert response.status_code == 502


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [e for e in _ENDPOINTS if e[1] in {"/api/status", "/api/write", "/api/power"}],
    ids=["status", "write", "power"],
)
def test_reply_without_a_response_for_the_request_is_502(
    *, stack: Stack, method: str, path: str, body: object
) -> None:
    stack.unit.reset()
    stack.unit.reply = HttpReply.json({"responses": []})

    response = stack.api.request(method, path=path, json=body)

    assert response.status_code == 502


def test_status_response_without_a_property_tree_is_502(stack: Stack) -> None:
    stack.unit.reset()
    stack.unit.reply = HttpReply.json(
        {"responses": [{"fr": dsiot.STATUS, "rsc": 2000}]}
    )

    response = stack.api.get("/api/status")

    assert response.status_code == 502


def test_raw_read_response_with_a_non_string_address_is_502(stack: Stack) -> None:
    """応答は応答元アドレス (fr) をキーにして返すので、fr が文字列でない応答は解釈できない。"""
    stack.unit.reset()
    stack.unit.reply = HttpReply.json({"responses": [{"fr": 1, "rsc": 2000}]})

    response = stack.api.post("/api/read", json={"targets": [dsiot.STATUS]})

    assert response.status_code == 502
