"""Encoding/decoding helpers for the Daikin ``dsiot`` local protocol.

Newer Daikin units (firmware using the "DAIKIN Smart App", here the MCK706A on
firmware ``3_15_0`` / api_ver ``2_2``) expose a single HTTP endpoint::

    POST http://<host>/dsiot/multireq

The body is JSON with a ``requests`` array. Each entry has an ``op`` (operation)
and a ``to`` (target path):

* ``op == 2`` -> read a property tree
* ``op == 3`` -> write a property tree (``pc``)

Responses come back as a tree of *property nodes*. Each node has:

* ``pn`` - property name (e.g. ``e_1002``, ``p_01``)
* ``pt`` - property type (``1`` == container with ``pch`` children, else leaf)
* ``pv`` - property value (leaf only)
* ``md`` - metadata; ``md.pt`` is the value encoding:
      ``"b"`` hex byte string, ``"i"`` integer, ``"s"`` plain string
  and ``md.mi`` / ``md.mx`` are the (hex) min / max bounds when applicable.

The protocol layer is intentionally free of any field semantics; the meaning of
individual ``e_*/p_*`` paths lives in :mod:`daikin.client`.
"""

from __future__ import annotations

from typing import Any

# Operation codes used on /dsiot/multireq.
OP_READ = 2
OP_WRITE = 3

# Per-request status code that means success.
RSC_OK = 2000


# --------------------------------------------------------------------------- #
# value decoding
# --------------------------------------------------------------------------- #
def hex_to_int(value: str, *, signed: bool = False) -> int:
    """Decode a little-endian hex byte string (``"3000"`` -> ``48``).

    dsiot stores numbers as little-endian byte strings of variable width.
    """
    raw = bytes.fromhex(value)
    return int.from_bytes(raw, "little", signed=signed)


def hex_to_temp(value: str) -> float:
    """Decode a temperature field: little-endian signed, in half-degrees.

    e.g. ``"3000"`` -> ``0x0030`` -> ``48`` -> ``24.0`` degC. Negative values
    use two's complement (``"EEFF"`` -> ``-18`` -> ``-9.0`` degC).
    """
    return hex_to_int(value, signed=True) / 2.0


def hex_to_ascii(value: str) -> str:
    """Decode a hex byte string into ASCII, trimming NUL padding.

    Several identity fields (model code, ssid suffix) are ASCII packed into a
    hex ``"b"`` value, e.g. ``"413530375F4B0000.."`` -> ``"A507_K"``.
    """
    text = bytes.fromhex(value).split(b"\x00", 1)[0]
    return text.decode("ascii", errors="replace")


# --------------------------------------------------------------------------- #
# response tree helpers
# --------------------------------------------------------------------------- #
def is_leaf(node: dict[str, Any]) -> bool:
    return "pch" not in node


def flatten(pc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Flatten a property container into ``{"e_1002/e_A002/p_01": node}``.

    The root container's own ``pn`` (e.g. ``dgc_status``) is dropped so paths
    start at its children. Returns ``{}`` for an empty/missing container.
    """
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
    """Return the raw ``pv`` of a leaf at ``path`` (or ``None`` if absent)."""
    node = flat.get(path)
    if node is None:
        return None
    return node.get("pv")


def build_read_requests(targets: list[str]) -> dict[str, Any]:
    """Build the JSON body for a batch of read (``op:2``) requests."""
    return {"requests": [{"op": OP_READ, "to": to} for to in targets]}


def build_write_request(to: str, entity_path: list[str], pv: str) -> dict[str, Any]:
    """Build a single write (``op:3``) request.

    ``entity_path`` is the chain of property names from the response root to the
    leaf (e.g. ``["e_1002", "e_A002", "p_01"]``); ``to`` is the dsiot address
    (e.g. ``"/dsiot/edge/adr_0100.dgc_status"``). The root container name is the
    last path segment of ``to`` after ``.``.
    """
    if not entity_path:
        raise ValueError("entity_path must not be empty")

    root_name = to.rsplit(".", 1)[-1]

    # Build from the leaf up: leaf carries pv, ancestors are containers (pt=1).
    node: dict[str, Any] = {"pn": entity_path[-1], "pt": 3, "pv": pv}
    for name in reversed(entity_path[:-1]):
        node = {"pn": name, "pt": 1, "pch": [node]}
    pc = {"pn": root_name, "pt": 1, "pch": [node]}

    return {"requests": [{"op": OP_WRITE, "to": to, "pc": pc}]}
