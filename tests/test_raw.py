"""POST /api/read と POST /api/write: 任意の dsiot アドレスの生読み取りと、任意プロパティへの生書き込み。"""

from typing import Any

import pytest
from hypothesis import given, strategies as st

from tests import dsiot
from tests.harness import HttpReply, Stack, Write, as_json

_json_values: st.SearchStrategy[Any] = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: (
        st.lists(children, max_size=3)
        | st.dictionaries(st.text(), children, max_size=3)
    ),
    max_leaves=8,
)
_segments = st.from_regex(r"[A-Za-z0-9_]+", fullmatch=True)
_addresses = st.tuples(
    st.from_regex(r"[a-z0-9_/]*[a-z0-9_]", fullmatch=True), _segments
).map(lambda parts: f"/dsiot/{parts[0]}.{parts[1]}")
# 本文から項目を除くことを表す。
_MISSING = object()
_WRITE: dict[str, object] = {
    "to": dsiot.STATUS,
    "entity_path": ["e_1002", "e_A002", "p_01"],
    "pv": "00",
    "confirm": True,
}


@given(
    # /dsiot/edge は README の、本体が持つ全アドレスを列挙するアドレス。
    pcs=st.dictionaries(
        _addresses | st.just("/dsiot/edge"),
        st.dictionaries(st.text(), _json_values, max_size=3),
        max_size=3,
    ),
    data=st.data(),
)
def test_read_returns_unit_responses_keyed_by_address(
    *, stack: Stack, pcs: dict[str, dict[str, Any]], data: st.DataObject
) -> None:
    # 本体が持つアドレス・持たないアドレス (rsc 4041)・重複・コンテナを指さないアドレスを混ぜて読む。
    targets = data.draw(
        st.lists(
            st.sampled_from([*pcs, dsiot.STATUS, "/dsiot/edge.none", "/dsiot/edge"]),
            min_size=1,
            max_size=4,
        )
    )
    stack.unit.reset()
    stack.unit.containers |= pcs
    expected: dict[str, Any] = {}
    for target in targets:
        if (pc := stack.unit.containers.get(target)) is None:
            expected[target] = {"fr": target, "rsc": 4041}
        else:
            expected[target] = {"fr": target, "pc": pc, "rsc": 2000}

    response = stack.api.post("/api/read", json={"targets": targets})

    assert response.status_code == 200
    assert as_json(response.json()) == as_json(expected)
    assert set(stack.unit.reads) == set(targets)


def test_read_returns_responses_without_a_result_code_as_is(stack: Stack) -> None:
    """/api/read は rsc を検査しない生の読み取りなので、rsc の無い応答も 200 でそのまま返す。"""
    stack.unit.reset()
    responses = [{"fr": dsiot.STATUS}, {"fr": dsiot.ADAPTER_INFO, "rsc": None}]
    stack.unit.reply = HttpReply.json({"responses": responses})

    response = stack.api.post(
        "/api/read", json={"targets": [dsiot.STATUS, dsiot.ADAPTER_INFO]}
    )

    assert response.status_code == 200
    assert as_json(response.json()) == as_json(
        {dsiot.STATUS: responses[0], dsiot.ADAPTER_INFO: responses[1]}
    )


@given(target=st.text().filter(lambda t: not t.startswith("/dsiot/")))
def test_read_of_address_outside_dsiot_is_rejected(
    *, stack: Stack, target: str
) -> None:
    stack.unit.reset()

    response = stack.api.post("/api/read", json={"targets": [dsiot.STATUS, target]})

    assert response.status_code == 422
    assert stack.unit.received == 0


@pytest.mark.parametrize(
    "targets",
    [[], ["/dsiot/../admin"], ["/dsiot/http://example.com/x"]],
    ids=["empty", "parent-segment", "url"],
)
def test_read_of_invalid_targets_is_rejected(
    *, stack: Stack, targets: list[str]
) -> None:
    stack.unit.reset()

    response = stack.api.post("/api/read", json={"targets": targets})

    assert response.status_code == 422
    assert stack.unit.received == 0


@given(
    to=_addresses,
    entity_path=st.lists(_segments, min_size=1, max_size=4),
    pv=st.binary(min_size=1, max_size=4).map(bytes.hex)
    | st.binary(min_size=1, max_size=4).map(lambda b: b.hex().upper()),
)
def test_write_sends_the_value_to_the_given_property(
    *, stack: Stack, to: str, entity_path: list[str], pv: str
) -> None:
    stack.unit.reset()
    container = to.rsplit(".", 1)[-1]
    stack.unit.containers[to] = dsiot.tree(
        container, leaves={"/".join(entity_path): {"pv": "00"}}
    )

    response = stack.api.post(
        "/api/write",
        json={"to": to, "entity_path": entity_path, "pv": pv, "confirm": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "written": {"to": to, "entity_path": entity_path, "pv": pv},
        "result": {"fr": to, "rsc": 2004},
    }
    assert stack.unit.writes == [Write(to, "/".join(entity_path), pv)]


def test_written_value_is_read_back_by_status(stack: Stack) -> None:
    stack.unit.reset()

    assert stack.api.post("/api/write", json=_WRITE).status_code == 200

    assert stack.api.get("/api/status").json()["power"] is False


def test_out_of_range_value_written_raw_can_be_found_and_restored(
    stack: Stack,
) -> None:
    """
    生書き込みは md.mx の範囲外の値も送る。保存された値で /api/status は 502 になるが、
    /api/tree で見つけ、対応する setter で戻せる (README「エラー」)。
    """
    stack.unit.reset()
    path = dsiot.HUMIDIFY.split("/")

    written = stack.api.post(
        "/api/write", json=_WRITE | {"entity_path": path, "pv": "01"}
    )

    assert written.status_code == 200
    assert stack.api.get("/api/status").status_code == 502
    assert stack.api.get("/api/tree").json()[dsiot.HUMIDIFY]["pv"] == "01"
    assert stack.api.post("/api/humidify", json={"on": False}).status_code == 200
    assert stack.api.get("/api/status").json()["humidify"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"confirm": _MISSING},
        {"confirm": None},
        {"confirm": False},
        {"confirm": "true"},
        {"confirm": 1},
        {"confirm": 1.0},
        {"pv": "1"},
        {"pv": ""},
        {"pv": "zz"},
        {"entity_path": []},
        {"entity_path": ["e_1002/e_A002", "p_01"]},
        {"to": "/dsiot/edge/adr_0100"},
        {"to": "/etc/passwd.x"},
        {"to": "/dsiot/../x.dgc_status"},
        {"extra": 1},
    ],
    ids=[
        "confirm-missing",
        "confirm-null",
        "confirm-false",
        "confirm-string",
        "confirm-integer",
        "confirm-float",
        "pv-odd-length",
        "pv-empty",
        "pv-not-hex",
        "entity-path-empty",
        "entity-path-with-slash",
        "to-without-container",
        "to-outside-dsiot",
        "to-parent-segment",
        "unknown-field",
    ],
)
def test_invalid_write_is_rejected_without_contacting_the_unit(
    *, stack: Stack, change: dict[str, object]
) -> None:
    stack.unit.reset()
    body = {k: v for k, v in (_WRITE | change).items() if v is not _MISSING}

    response = stack.api.post("/api/write", json=body)

    assert response.status_code == 422
    assert stack.unit.received == 0


def test_write_rejected_by_the_unit_is_502_with_its_rsc(stack: Stack) -> None:
    stack.unit.reset()
    stack.unit.write_rsc = 4000

    response = stack.api.post("/api/write", json=_WRITE)

    assert response.status_code == 502
    assert response.json()["rsc"] == 4000


@pytest.mark.parametrize(
    ("rsc", "status_code"),
    [(1999, 502), *((rsc, 200) for rsc in range(2000, 2010)), (2010, 502)],
)
def test_write_succeeds_only_with_a_200x_result_code(
    *, stack: Stack, rsc: int, status_code: int
) -> None:
    """本体の rsc は 200x が成功 (README「仕組み」)。"""
    stack.unit.reset()
    stack.unit.write_rsc = rsc

    response = stack.api.post("/api/write", json=_WRITE)

    assert response.status_code == status_code
