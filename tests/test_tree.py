"""GET /api/tree: dgc_status の全リーフを、ルートからのパスをキーにして生の値・復号値・メタ情報とともに返す。"""

from typing import Any, cast

import pytest
from hypothesis import given, strategies as st

from tests import dsiot
from tests.harness import Stack, as_json

# 名前は `/` を含まない (パスの区切りに使う)。
_names = st.text(
    st.characters(codec="utf-8", exclude_characters="/"), min_size=1, max_size=6
)
# 実機のリーフは設定値が pt 2、センサーと固定情報が pt 3 (docs/dsiot.md「リクエストとレスポンス」)。
_leaf_types = st.sampled_from([2, 3])
_hex_meta = st.fixed_dictionaries(
    {"pt": st.just("b")},
    optional={
        "mi": st.binary(max_size=2).map(bytes.hex),
        "mx": st.binary(max_size=2).map(bytes.hex),
    },
)


@st.composite
def _hex_leaf(draw: st.DrawFn) -> tuple[dict[str, Any], dict[str, Any]]:
    """16 進バイト列のリーフと、その期待値 (ascii を除く)。"""
    raw = draw(st.binary(min_size=1, max_size=4))
    pv = draw(st.sampled_from([raw.hex(), raw.hex().upper()]))
    md = draw(_hex_meta)
    leaf = {"pv": pv, "md": md, "pt": draw(_leaf_types)}
    expected = {
        "pv": pv,
        "value": int.from_bytes(raw, "little"),
        "type": "b",
        "min": md.get("mi"),
        "max": md.get("mx"),
    }
    return leaf, expected


@st.composite
def _other_leaf(draw: st.DrawFn) -> tuple[dict[str, Any], dict[str, Any]]:
    """16 進バイト列でないリーフ (整数・文字列・メタ情報の無いもの) と、その期待値 (ascii を除く)。値は pv のまま。"""
    pv = draw(st.none() | st.integers() | st.text())
    md = draw(
        st.none()
        | st.fixed_dictionaries({}, optional={"pt": st.sampled_from(["i", "s"])})
    )
    leaf: dict[str, Any] = {"pv": pv, "pt": draw(_leaf_types)}
    if md is not None:
        leaf["md"] = md
    meta = md or {}
    expected = {"pv": pv, "value": pv, "type": meta.get("pt"), "min": None, "max": None}
    return leaf, expected


_leaves = _hex_leaf() | _other_leaf()
# 子の名前 → リーフ (tuple) か子のコンテナ (dict)。
_containers = st.recursive(
    st.dictionaries(_names, _leaves, max_size=3),
    lambda children: st.dictionaries(_names, _leaves | children, max_size=3),
    max_leaves=10,
)


def _flatten(
    container: dict[str, Any], *, prefix: str = ""
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """コンテナを、pc の pch と、リーフのパス → 期待値に分ける。"""
    pch: list[dict[str, Any]] = []
    expected: dict[str, dict[str, Any]] = {}
    for name, child in container.items():
        path = f"{prefix}/{name}" if prefix else name
        if isinstance(child, dict):
            grand_pch, grand_expected = _flatten(
                cast("dict[str, Any]", child), prefix=path
            )
            pch.append({"pn": name, "pt": 1, "pch": grand_pch})
            expected |= grand_expected
        else:
            leaf, leaf_expected = child
            pch.append({"pn": name, **leaf})
            expected[path] = leaf_expected
    return pch, expected


@given(container=_containers)
def test_tree_returns_every_leaf_by_its_path(
    *, stack: Stack, container: dict[str, Any]
) -> None:
    stack.unit.reset()
    pch, expected = _flatten(container)
    stack.unit.containers[dsiot.STATUS] = {"pn": "dgc_status", "pt": 1, "pch": pch}

    response = stack.api.get("/api/tree")

    assert response.status_code == 200
    body = response.json()
    assert as_json(
        {
            path: {k: v for k, v in leaf.items() if k != "ascii"}
            for path, leaf in body.items()
        }
    ) == as_json(expected)


@pytest.mark.parametrize(
    ("pv", "ascii_text"),
    [("30302D3030", "00-00"), ("41420000", "AB"), ("01", None)],
    ids=["error-code", "nul-terminated", "non-printable"],
)
def test_tree_reads_hex_values_as_nul_terminated_ascii(
    *, stack: Stack, pv: str, ascii_text: str | None
) -> None:
    stack.unit.reset()
    stack.unit.containers[dsiot.STATUS] = dsiot.tree(
        "dgc_status", leaves={"e_1002/p_09": dsiot.hex_leaf(pv)}
    )

    response = stack.api.get("/api/tree")

    assert response.status_code == 200
    assert response.json()["e_1002/p_09"]["ascii"] == ascii_text


def test_tree_returns_hex_typed_values_that_are_not_hex_as_is(stack: Stack) -> None:
    stack.unit.reset()
    stack.unit.containers[dsiot.STATUS] = dsiot.tree(
        "dgc_status", leaves={"p_01": dsiot.hex_leaf("zz")}
    )

    response = stack.api.get("/api/tree")

    assert response.status_code == 200
    assert response.json()["p_01"] == {
        "pv": "zz",
        "value": "zz",
        "type": "b",
        "min": None,
        "max": None,
        "ascii": None,
    }


@pytest.mark.parametrize(
    "pch",
    [
        "not a list",
        ["not an object"],
        [{"pv": "00"}],
        [{"pn": "", "pv": "00"}],
        [{"pn": "p_01", "pv": "00", "md": "not an object"}],
    ],
    ids=[
        "pch-not-list",
        "node-not-object",
        "node-without-name",
        "empty-name",
        "md-not-object",
    ],
)
def test_tree_with_malformed_property_tree_is_502(*, stack: Stack, pch: object) -> None:
    stack.unit.reset()
    stack.unit.containers[dsiot.STATUS] = {"pn": "dgc_status", "pt": 1, "pch": pch}

    response = stack.api.get("/api/tree")

    assert response.status_code == 502
