"""
dsiot のワイヤフォーマット: multireq 本文の組み立てと、応答のプロパティツリーの読み取り。

機種に依存しない。MCK706A 固有のアドレスやプロパティパスは client.py が持つ。
"""

from collections.abc import Callable, Sequence
from typing import Any, TypeIs, cast

from daikin.exceptions import DaikinError

OP_READ = 2
OP_WRITE = 3
# 公式アプリは 200x を全て成功扱いにする。MCK706A は書き込み成功時に 2004 を返す。
RSC_SUCCESS = range(2000, 2010)


def hex_to_int(value: str, *, signed: bool = False) -> int:
    """リトルエンディアンの 16 進文字列 (md.pt == "b" のリーフ) を整数にする。"""
    return int.from_bytes(bytes.fromhex(value), "little", signed=signed)


def hex_to_bool(value: str) -> bool:
    return hex_to_int(value) != 0


def int_to_hex(value: int, *, length: int) -> str:
    """整数を length バイトのリトルエンディアン 16 進文字列 (pv の形式) にする。"""
    return value.to_bytes(length, "little").hex().upper()


def hex_to_temp(value: str) -> float:
    """int16 LE の 0.5 ℃ 単位を ℃ にする。"""
    return hex_to_int(value, signed=True) / 2


def hex_to_ascii(value: str) -> str | None:
    """
    16 進バイト列を最初の NUL までの ASCII 文字列として読む。

    印字可能な英数字を含む文字列に見えないときは None。
    """
    raw = bytes.fromhex(value).split(b"\x00", 1)[0]
    if not raw.isascii():
        return None
    text = raw.decode("ascii")
    if text.isprintable() and any(c.isalnum() for c in text):
        return text
    return None


def int_to_bool(value: int | str) -> bool:
    """整数リーフ (md.pt == "i"。JSON の int または 10 進文字列) を bool にする。"""
    return int(value) != 0


def is_json_object(value: object) -> TypeIs[dict[str, Any]]:
    """JSON から読んだ値が object か。JSON の object のキーは常に str。"""
    return isinstance(value, dict)


class PropertyTree:
    """
    multireq 応答の pc を、リーフのパス ("e_1002/e_A002/p_01") で引ける形にしたもの。

    パスにルート (dgc_status 等) 自身の名前は含まない。`pch` がリストでない、`pch` の中のノードが object でない、
    またはそのノードの `pn` が文字列でない `pc` を渡すと DaikinError を送出する。
    """

    def __init__(self, pc: dict[str, Any]) -> None:
        self.leaves: dict[str, dict[str, Any]] = {}
        self._collect(pc.get("pch", []), prefix="")

    def _collect(self, nodes: object, *, prefix: str) -> None:
        where = f"under {prefix!r}" if prefix else "under the root"
        if not isinstance(nodes, list):
            raise DaikinError(f'"pch" {where} is not a list: {nodes!r}')
        for node in cast("list[object]", nodes):
            if not is_json_object(node):
                raise DaikinError(f"Node {where} is not an object: {node!r}")
            name = node.get("pn", "")
            if not isinstance(name, str):
                raise DaikinError(f'"pn" {where} is not a string: {name!r}')
            path = f"{prefix}/{name}" if prefix else name
            if "pch" in node:
                self._collect(node["pch"], prefix=path)
            else:
                self.leaves[path] = node

    def pv(self, path: str) -> object:
        """リーフの生の値。リーフが無ければ None。"""
        node = self.leaves.get(path)
        return None if node is None else node.get("pv")

    def decode[T](self, path: str, *, decoder: Callable[[Any], T]) -> T | None:
        """
        リーフの pv を decoder で変換する。リーフが無い、または pv が None なら None。

        Raises:
            DaikinError: pv が decoder の想定する形でない。
        """
        if (pv := self.pv(path)) is None:
            return None
        try:
            return decoder(pv)
        except (ValueError, TypeError) as err:
            raise DaikinError(f"Cannot decode {path}={pv!r}: {err}") from err


def build_read_requests(targets: Sequence[str]) -> dict[str, Any]:
    return {"requests": [{"op": OP_READ, "to": to} for to in targets]}


def build_write_request(
    to: str, *, entity_path: Sequence[str], pv: str
) -> dict[str, Any]:
    """to のコンテナ配下で entity_path が指すリーフだけを持つ書き込み本文を組む。"""
    if not entity_path:
        raise ValueError("entity_path must not be empty")
    node: dict[str, Any] = {"pn": entity_path[-1], "pt": 3, "pv": pv}
    for name in reversed(entity_path[:-1]):
        node = {"pn": name, "pt": 1, "pch": [node]}
    pc = {"pn": to.rsplit(".", 1)[-1], "pt": 1, "pch": [node]}
    return {"requests": [{"op": OP_WRITE, "to": to, "pc": pc}]}
