"""Standalone client for the Daikin MCK706A local ``dsiot`` API.

This subpackage is independent of the FastAPI layer and can be used on its own::

    from daikin import DaikinClient
    c = DaikinClient("http://172.16.1.114")
    print(c.air_status())

There is no login / authentication: the unit answers any LAN client.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests

from .exceptions import DaikinConnectionError, DaikinError
from .protocol import (
    RSC_OK,
    build_read_requests,
    build_write_request,
    flatten,
    hex_to_ascii,
    hex_to_int,
    hex_to_temp,
    leaf_pv,
)

# dsiot addresses on this unit.
ADDR_STATUS = "/dsiot/edge/adr_0100.dgc_status"  # control + sensors
ADDR_STATUS2 = "/dsiot/edge/adr_0200.dgc_status"  # (empty on MCK706A, kept for parity)
ADDR_INFO = "/dsiot/edge.adp_i"  # adapter info (fw, mac, ssid, ...)
ADDR_DEVICE = "/dsiot/edge.adp_d"  # device settings (name, led, timezone, ...)

# --------------------------------------------------------------------------- #
# Field map (paths are relative to the dgc_status root, i.e. under e_1002).
#
# Confidently decoded (verified against the unit / matches the BRP084 protocol):
#   power, temperature, humidity.
# Best-effort (range known, exact label not publicly documented for the MCK
#   line): mode, fan_rate, and the dynamic "monitor" values below. The full
#   decoded tree is always available via :meth:`status_tree` for correlation.
# --------------------------------------------------------------------------- #
P_POWER = "e_1002/e_A002/p_01"  # 00/01 -> off/on
P_TEMPERATURE = "e_1002/e_A00B/p_01"  # int16 LE, half-degrees C
P_HUMIDITY = "e_1002/e_A00B/p_02"  # uint8, %RH
P_MODE = "e_1002/e_3001/p_3F"  # 0..5 operation mode (raw)
P_FAN_RATE = "e_1002/e_3007/p_32"  # 0..7 airflow level (raw)

# Dynamic air-quality monitors (values observed to fluctuate over time). Exact
# units are not publicly documented for the MCK706A; exposed as decoded ints.
MONITORS = {
    "monitor_a": "e_1002/e_3007/p_3A",
    "monitor_b": "e_1002/e_3007/p_3B",
    "pm_a": "e_1002/e_205E/p_01",
    "pm_b": "e_1002/e_205E/p_02",
}


class DaikinClient:
    def __init__(self, host: str, *, timeout: int = 10) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------ #
    # transport
    # ------------------------------------------------------------------ #
    def _multireq(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{self.host}/dsiot/multireq"
        try:
            resp = self._session.post(
                url,
                json=body,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
        except requests.exceptions.RequestException as err:
            raise DaikinConnectionError(
                f"Cannot reach Daikin unit at {self.host}: {err}"
            ) from err

        try:
            payload = resp.json()
        except ValueError as err:
            raise DaikinError(
                f"Non-JSON response from {url}: {resp.text[:200]}"
            ) from err

        responses = payload.get("responses")
        if not isinstance(responses, list):
            raise DaikinError(f"Unexpected dsiot response: {payload!r}")
        return responses

    def read(self, targets: list[str]) -> dict[str, dict[str, Any]]:
        """Read one or more dsiot addresses; returns ``{address: response}``."""
        responses = self._multireq(build_read_requests(targets))
        return {r.get("fr", ""): r for r in responses}

    def read_one(self, target: str) -> dict[str, Any]:
        """Read a single address and return its (raw) response object."""
        resp = self.read([target]).get(target)
        if resp is None:
            raise DaikinError(f"No response for {target}")
        if resp.get("rsc") not in (None, RSC_OK):
            raise DaikinError(
                f"Read of {target} returned rsc={resp.get('rsc')}",
                rsc=resp.get("rsc"),
            )
        return resp

    def write(self, to: str, entity_path: list[str], pv: str) -> dict[str, Any]:
        """Write a single property (``op:3``) and return the response object.

        ``pv`` is the little-endian hex value to store (e.g. ``"00"`` / ``"01"``).
        Raises :class:`DaikinError` if the unit reports a non-OK status.
        """
        body = build_write_request(to, entity_path, pv)
        responses = self._multireq(body)
        resp = responses[0] if responses else {}
        if resp.get("rsc") not in (None, RSC_OK):
            raise DaikinError(
                f"Write to {to} ({'/'.join(entity_path)}) returned "
                f"rsc={resp.get('rsc')}",
                rsc=resp.get("rsc"),
            )
        return resp

    # ------------------------------------------------------------------ #
    # high level reads
    # ------------------------------------------------------------------ #
    def device_info(self) -> dict[str, Any]:
        """Adapter / device identity (firmware, mac, name, led, timezone)."""
        data = self.read([ADDR_INFO, ADDR_DEVICE])
        info = flatten(data.get(ADDR_INFO, {}).get("pc"))
        dev = flatten(data.get(ADDR_DEVICE, {}).get("pc"))

        return {
            "name": leaf_pv(dev, "name"),
            "mac": leaf_pv(info, "mac"),
            "firmware": leaf_pv(info, "ver"),
            "revision": leaf_pv(info, "rev"),
            "region": leaf_pv(info, "reg"),
            "ssid": leaf_pv(info, "ssid"),
            "api_ver": leaf_pv(info, "api_ver"),
            "led": _as_bool(leaf_pv(dev, "led")),
            "timezone_offset_min": leaf_pv(dev, "timz/tmdf"),
        }

    def status_tree(self) -> dict[str, Any]:
        """The full ``adr_0100.dgc_status`` tree, decoded leaf-by-leaf.

        Every leaf becomes ``{path: {"pv", "value", "type", "min", "max"}}``
        where ``value`` is the decoded number (or ASCII) where possible. Useful
        for exploring fields whose meaning is not yet mapped.
        """
        resp = self.read_one(ADDR_STATUS)
        flat = flatten(resp.get("pc"))
        out: dict[str, Any] = {}
        for path, node in flat.items():
            out[path] = _decode_leaf(node)
        return out

    def air_status(self) -> dict[str, Any]:
        """Current air / operating state with the confidently-decoded fields."""
        resp = self.read_one(ADDR_STATUS)
        flat = flatten(resp.get("pc"))

        monitors = {
            label: _decode_pv(flat, path, hex_to_int)
            for label, path in MONITORS.items()
        }

        return {
            "power": _decode_pv(flat, P_POWER, lambda v: _as_bool(hex_to_int(v))),
            "temperature_c": _decode_pv(flat, P_TEMPERATURE, hex_to_temp),
            "humidity_pct": _decode_pv(flat, P_HUMIDITY, hex_to_int),
            "mode": _decode_pv(flat, P_MODE, hex_to_int),
            "fan_rate": _decode_pv(flat, P_FAN_RATE, hex_to_int),
            "monitors": monitors,
        }

    # ------------------------------------------------------------------ #
    # high level writes (best-effort; the protocol is undocumented)
    # ------------------------------------------------------------------ #
    def set_power(self, on: bool) -> dict[str, Any]:
        """Turn the purifier on/off via ``e_A002/p_01``."""
        return self.write(ADDR_STATUS, P_POWER.split("/"), "01" if on else "00")


# --------------------------------------------------------------------------- #
# module helpers
# --------------------------------------------------------------------------- #
def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(int(value))


def _decode_pv(
    flat: dict[str, dict[str, Any]],
    path: str,
    decoder: Callable[[str], Any],
) -> Any:
    """Read the raw ``pv`` at ``path`` and decode it, or ``None`` if absent."""
    raw = leaf_pv(flat, path)
    return decoder(raw) if raw is not None else None


def _decode_leaf(node: dict[str, Any]) -> dict[str, Any]:
    """Decode a single leaf node into pv + best-effort value + bounds."""
    pv = node.get("pv")
    md = node.get("md") or {}
    md_pt = md.get("pt")

    value: Any = pv
    if md_pt == "b" and isinstance(pv, str) and pv != "":
        try:
            value = hex_to_int(pv)
        except ValueError:
            value = pv
    elif md_pt in ("i", "s"):
        value = pv

    out: dict[str, Any] = {"pv": pv, "value": value, "type": md_pt}
    if md.get("mi") is not None:
        out["min"] = md["mi"]
    if md.get("mx") is not None:
        out["max"] = md["mx"]
    # Surface an ASCII rendering for hex strings that look like text.
    if md_pt == "b" and isinstance(pv, str) and pv:
        ascii_val = hex_to_ascii(pv)
        if ascii_val.isprintable() and any(c.isalnum() for c in ascii_val):
            out["ascii"] = ascii_val
    return out
