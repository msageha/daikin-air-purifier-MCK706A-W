"""本文を受け取る全 endpoint の共通の検証: 要求として読めない本文は、本体に送らずに 422 にする。"""

import pytest

from tests.harness import Stack

_PATHS = [
    "/api/read",
    "/api/write",
    "/api/power",
    "/api/humidify",
    "/api/course",
    "/api/fan-speed",
    "/api/humidity-setting",
]


@pytest.mark.parametrize(
    "body",
    [b"", b"not json", b"[]", b'"on"', b'{"on": NaN, "course": NaN}'],
    ids=["empty", "not-json", "array", "string", "nan-fields"],
)
@pytest.mark.parametrize("path", _PATHS)
def test_body_that_is_not_a_valid_request_is_422(
    *, stack: Stack, path: str, body: bytes
) -> None:
    """JSON でない本文・object でない本文・項目が JSON の値でない (NaN) 本文。"""
    stack.unit.reset()

    response = stack.api.post_bytes(path, body=body)

    assert response.status_code == 422
    assert stack.unit.received == 0


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/read", rb'{"targets": ["/dsiot/edge\ud800.adp_i"]}'),
        (
            "/api/write",
            rb'{"to": "/dsiot/edge\ud800.adp_i", "entity_path": ["p_01"], "pv": "00", "confirm": true}',
        ),
    ],
    ids=["read", "write"],
)
def test_address_that_is_not_valid_unicode_is_422(
    *, stack: Stack, path: str, body: bytes
) -> None:
    """JSON の構文は孤立した surrogate を通すが、UTF-8 で表せない文字列はアドレスとして受け付けない。"""
    stack.unit.reset()

    response = stack.api.post_bytes(path, body=body)

    assert response.status_code == 422
    assert stack.unit.received == 0


def test_rejected_value_is_reported_in_the_422_detail(stack: Stack) -> None:
    """JSON にできる入力値は、FastAPI の既定の 422 と同じく detail の input に入る。"""
    stack.unit.reset()

    response = stack.api.post("/api/course", json={"course": "unknown"})

    assert response.status_code == 422
    assert [e.get("input") for e in response.json()["detail"]] == ["unknown"]
