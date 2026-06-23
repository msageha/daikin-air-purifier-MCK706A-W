from __future__ import annotations

from collections.abc import Sequence
from typing import Any

OP_READ = 2
OP_WRITE = 3

RSC_OK = 2000


def hex_to_int(value: str, *, signed: bool = False) -> int:
    raw = bytes.fromhex(value)
    return int.from_bytes(raw, "little", signed=signed)


def hex_to_temp(value: str) -> float:
    return hex_to_int(value, signed=True) / 2.0


def hex_to_ascii(value: str) -> str:
    text = bytes.fromhex(value).split(b"\x00", 1)[0]
    return text.decode("ascii", errors="replace")


def is_leaf(node: dict[str, Any]) -> bool:
    return "pch" not in node


def flatten(pc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not pc:
        return out

    def _walk(node: dict[str, Any], prefix: str) -> None:
        if is_leaf(node):
            out[prefix] = node
            return
        for child in node.get("pch", []):
            name = child.get("pn", "")
            child_prefix = f"{prefix}/{name}" if prefix else name
            _walk(child, child_prefix)

    for child in pc.get("pch", []):
        _walk(child, child.get("pn", ""))
    return out


def leaf_pv(flat: dict[str, dict[str, Any]], path: str) -> str | None:
    node = flat.get(path)
    if node is None:
        return None
    return node.get("pv")


def build_read_requests(targets: list[str]) -> dict[str, Any]:
    return {"requests": [{"op": OP_READ, "to": to} for to in targets]}


def build_write_request(to: str, entity_path: Sequence[str], pv: str) -> dict[str, Any]:
    if not entity_path:
        raise ValueError("entity_path must not be empty")

    root_name = to.rsplit(".", 1)[-1]

    node: dict[str, Any] = {"pn": entity_path[-1], "pt": 3, "pv": pv}
    for name in reversed(entity_path[:-1]):
        node = {"pn": name, "pt": 1, "pch": [node]}
    pc = {"pn": root_name, "pt": 1, "pch": [node]}

    return {"requests": [{"op": OP_WRITE, "to": to, "pc": pc}]}
