"""GET /api/info: adp_i・adp_d・adp_r・dev_i から機器・アダプタ情報を集めて返す。"""

from typing import Any

from hypothesis import given, strategies as st

from tests import dsiot
from tests.harness import Stack, as_json

# API のフィールド → (アドレス, リーフのパス)。
_TEXT_FIELDS = {
    "name": (dsiot.USER_SETTINGS, "name"),
    "device_type": (dsiot.DEVICE_TYPE, "type"),
    "mac": (dsiot.ADAPTER_INFO, "mac"),
    "firmware": (dsiot.ADAPTER_INFO, "ver"),
    "revision": (dsiot.ADAPTER_INFO, "rev"),
    "region": (dsiot.ADAPTER_INFO, "reg"),
    "ssid": (dsiot.ADAPTER_INFO, "ssid"),
    "wlan_ssid": (dsiot.WIRELESS, "wlan_info/ssid"),
    "api_ver": (dsiot.ADAPTER_INFO, "api_ver"),
}
_INT_FIELDS = {
    "wlan_rssi_dbm": (dsiot.WIRELESS, "wlan_info/rssi"),
    "timezone_offset_min": (dsiot.USER_SETTINGS, "timz/tmdf"),
}
_LED = (dsiot.USER_SETTINGS, "led")
_ROOTS = {
    dsiot.ADAPTER_INFO: "adp_i",
    dsiot.USER_SETTINGS: "adp_d",
    dsiot.WIRELESS: "adp_r",
    dsiot.DEVICE_TYPE: "dev_i",
}


def _set_leaves(stack: Stack, *, pvs: dict[tuple[str, str], Any]) -> None:
    """(アドレス, パス) → pv の対応で 4 つのアドレスのツリーを作り直す。pv が None のリーフは置かない。"""
    for address, root in _ROOTS.items():
        leaves = {
            path: {"pv": pv}
            for (where, path), pv in pvs.items()
            if where == address and pv is not None
        }
        stack.unit.containers[address] = dsiot.tree(root, leaves=leaves)


@given(
    texts=st.fixed_dictionaries({name: st.none() | st.text() for name in _TEXT_FIELDS}),
    ints=st.fixed_dictionaries(
        {name: st.none() | st.integers(-(2**31), 2**31) for name in _INT_FIELDS}
    ),
    # LED は整数のリーフ (md.pt = "i") で、JSON の整数か 10 進の文字列で届く。
    led=st.none() | st.integers(0, 1) | st.integers(0, 1).map(str),
)
def test_info_collects_fields_from_the_adapter_addresses(
    *,
    stack: Stack,
    texts: dict[str, str | None],
    ints: dict[str, int | None],
    led: int | str | None,
) -> None:
    stack.unit.reset()
    pvs: dict[tuple[str, str], Any] = {_LED: led}
    pvs |= {_TEXT_FIELDS[name]: value for name, value in texts.items()}
    pvs |= {_INT_FIELDS[name]: value for name, value in ints.items()}
    _set_leaves(stack, pvs=pvs)

    response = stack.api.get("/api/info")

    assert response.status_code == 200
    assert as_json(response.json()) == as_json(
        {
            **texts,
            **ints,
            "led": None if led is None else int(led) != 0,
        }
    )


def test_info_with_a_missing_address_is_502_with_its_rsc(stack: Stack) -> None:
    stack.unit.reset()
    del stack.unit.containers[dsiot.WIRELESS]

    response = stack.api.get("/api/info")

    assert response.status_code == 502
    assert response.json()["rsc"] == 4041


def test_info_with_a_value_of_the_wrong_type_is_502(stack: Stack) -> None:
    stack.unit.reset()
    _set_leaves(stack, pvs={_INT_FIELDS["wlan_rssi_dbm"]: "strong"})

    response = stack.api.get("/api/info")

    assert response.status_code == 502
