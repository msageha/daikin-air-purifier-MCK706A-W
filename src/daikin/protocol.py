"""dsiot のワイヤフォーマット: multireq 本文の組み立てと、応答のプロパティツリーの読み取り。

機種に依存しない。MCK706A 固有のアドレスやプロパティパスは client.py が持つ。
"""

from collections.abc import Callable, Sequence
from typing import Any

from .exceptions import DaikinError

OP_READ = 2
OP_WRITE = 3
# 公式アプリは 200x を全て成功扱いにする。MCK706A は書き込み成功時に 2004 を返す。
RSC_SUCCESS = range(2000, 2010)


def hex_to_int(value: str, *, signed: bool = False) -> int:
    """リトルエンディアンの 16 進文字列 (md.pt == "b" のリーフ) を整数にする。"""
    return int.from_bytes(bytes.fromhex(value), "little", signed=signed)


def hex_to_bool(value: str) -> bool:
    return hex_to_int(value) != 0


def int_to_hex(value: int, length: int) -> str:
    """整数を length バイトのリトルエンディアン 16 進文字列 (pv の形式) にする。"""
    return value.to_bytes(length, "little").hex().upper()


def hex_to_temp(value: str) -> float:
    """int16 LE の 0.5 ℃ 単位を ℃ にする。"""
    return hex_to_int(value, signed=True) / 2


def hex_to_ascii(value: str) -> str | None:
    """16 進バイト列を最初の NUL までの ASCII 文字列として読む。

    印字可能な英数字を含む文字列に見えないときは None。
    """
    raw = bytes.fromhex(value).split(b"\x00", 1)[0]
    if not raw.isascii():
        return None
    text = raw.decode("ascii")
    if text.isprintable() and any(c.isalnum() for c in text):
        return text
    return None


def int_to_bool(value: Any) -> bool:
    """整数リーフ (md.pt == "i"。JSON の int または 10 進文字列) を bool にする。"""
    return int(value) != 0


class PropertyTree:
    """multireq 応答の pc を、リーフのパス ("e_1002/e_A002/p_01") で引ける形にしたもの。

    パスにルート (dgc_status 等) 自身の名前は含まない。
    """

    def __init__(self, pc: dict[str, Any]) -> None:
        self.leaves: dict[str, dict[str, Any]] = {}
        self._collect(pc.get("pch", []), "")

    def _collect(self, nodes: list[dict[str, Any]], prefix: str) -> None:
        for node in nodes:
            name = node.get("pn", "")
            path = f"{prefix}/{name}" if prefix else name
            if "pch" in node:
                self._collect(node["pch"], path)
            else:
                self.leaves[path] = node

    def pv(self, path: str) -> Any:
        """リーフの生の値。リーフが無ければ None。"""
        node = self.leaves.get(path)
        return None if node is None else node.get("pv")

    def decode[T](self, path: str, decoder: Callable[[Any], T]) -> T | None:
        """リーフの pv を decoder で変換する。リーフが無い、または pv が None なら None。

        Raises:
            DaikinError: pv が decoder の想定する形でない。
        """
        pv = self.pv(path)
        if pv is None:
            return None
        try:
            return decoder(pv)
        except (ValueError, TypeError) as err:
            raise DaikinError(f"Cannot decode {path}={pv!r}: {err}") from err


def build_read_requests(targets: Sequence[str]) -> dict[str, Any]:
    return {"requests": [{"op": OP_READ, "to": to} for to in targets]}


def build_write_request(to: str, entity_path: Sequence[str], pv: str) -> dict[str, Any]:
    """to のコンテナ配下で entity_path が指すリーフだけを持つ書き込み本文を組む。"""
    if not entity_path:
        raise ValueError("entity_path must not be empty")
    node: dict[str, Any] = {"pn": entity_path[-1], "pt": 3, "pv": pv}
    for name in reversed(entity_path[:-1]):
        node = {"pn": name, "pt": 1, "pch": [node]}
    pc = {"pn": to.rsplit(".", 1)[-1], "pt": 1, "pch": [node]}
    return {"requests": [{"op": OP_WRITE, "to": to, "pc": pc}]}
