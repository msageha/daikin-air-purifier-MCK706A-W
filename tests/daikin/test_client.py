from daikin.client import (
    ADDR_ADAPTER_RUNTIME,
    ADDR_DEVICE,
    ADDR_DEVICE_TYPE,
    ADDR_INFO,
    ADDR_STATUS,
    DaikinClient,
)
from daikin.models import Course, FanSpeed, HumiditySetting

# A trimmed adr_0100.dgc_status tree carrying every field air_status decodes.
STATUS_PC = {
    "pn": "dgc_status",
    "pt": 1,
    "pch": [
        {
            "pn": "e_1002",
            "pt": 1,
            "pch": [
                {
                    "pn": "e_A002",
                    "pt": 1,
                    "pch": [
                        {"pn": "p_01", "pv": "01", "md": {"pt": "b"}},
                    ],
                },
                {
                    "pn": "e_A004",
                    "pt": 1,
                    "pch": [
                        {"pn": "p_09", "pv": "30302D3030", "md": {"pt": "b"}},
                    ],
                },
                {
                    "pn": "e_A00B",
                    "pt": 1,
                    "pch": [
                        {"pn": "p_01", "pv": "3000", "md": {"pt": "b"}},
                        {"pn": "p_02", "pv": "41", "md": {"pt": "b"}},
                    ],
                },
                {
                    "pn": "e_3001",
                    "pt": 1,
                    "pch": [
                        # humidify + purify; md.mx=05 means only 00 and 02 are supported
                        {"pn": "p_3F", "pv": "02", "md": {"pt": "b", "mx": "05"}},
                        {"pn": "p_40", "pv": "00", "md": {"pt": "b"}},
                    ],
                },
                {
                    "pn": "e_3007",
                    "pt": 1,
                    "pch": [
                        # purify-side course: smart; supported = smart..pollen, circulator
                        {"pn": "p_01", "pv": "0000", "md": {"pt": "b", "mx": "5F00"}},
                        # humidify-side course: pollen; supported = smart..circulator
                        {"pn": "p_03", "pv": "0400", "md": {"pt": "b", "mx": "7F00"}},
                        # fan speeds: quiet / turbo; supported = quiet, low, standard, turbo
                        {"pn": "p_04", "pv": "00", "md": {"pt": "b", "mx": "17"}},
                        {"pn": "p_06", "pv": "04", "md": {"pt": "b", "mx": "17"}},
                        # humidity setting for manual / pollen; supported = low..high
                        {"pn": "p_13", "pv": "01", "md": {"pt": "b", "mx": "0E"}},
                        {"pn": "p_16", "pv": "03", "md": {"pt": "b", "mx": "0E"}},
                        {"pn": "p_1D", "pv": "02", "md": {"pt": "b"}},
                        {"pn": "p_1E", "pv": "01", "md": {"pt": "b"}},
                        {"pn": "p_1F", "pv": "00", "md": {"pt": "b"}},
                        {"pn": "p_20", "pv": "01", "md": {"pt": "b"}},
                        {"pn": "p_26", "pv": "930200", "md": {"pt": "b"}},
                        {"pn": "p_27", "pv": "700200", "md": {"pt": "b"}},
                        {"pn": "p_28", "pv": "FA0300", "md": {"pt": "b"}},
                        {"pn": "p_29", "pv": "00", "md": {"pt": "b"}},
                        {"pn": "p_3E", "pv": "00", "md": {"pt": "b"}},
                    ],
                },
            ],
        }
    ],
}


def _read_returning(by_address):
    """address -> pc の対応から、DaikinClient.read の代わりになる関数を作る。"""
    return lambda targets: {
        addr: {"fr": addr, "rsc": 2000, "pc": pc} for addr, pc in by_address.items()
    }


def test_air_status_decodes_known_fields(monkeypatch):
    client = DaikinClient("http://unit")
    monkeypatch.setattr(client, "read", _read_returning({ADDR_STATUS: STATUS_PC}))

    status = client.air_status()

    assert status.power is True  # 0x01
    assert status.humidify is True  # p_3F = 02
    # humidify is on, so course / fan speed come from the humidify-side p_03 / p_06
    assert status.course is Course.POLLEN  # 0x0004 LE
    assert status.fan_speed is FanSpeed.TURBO
    assert status.humidity_setting is HumiditySetting.HIGH  # p_16 for pollen
    assert status.temperature_c == 24.0  # 0x0030 LE = 48, half-degrees
    assert status.humidity_pct == 65  # 0x41
    assert status.pm25_level == 2
    assert status.dust_level == 1
    assert status.odor_level == 0
    assert status.pm25_raw == 659  # 0x000293 LE
    assert status.dust_raw == 624
    assert status.odor_raw == 1018
    assert status.water_supply_sign is True
    assert status.filter_drying is False
    assert status.deodorizing_filter_off_sign is False
    assert status.streamer_maintenance_sign is False
    assert status.error_code == "00-00"


def test_air_status_missing_fields_become_none(monkeypatch):
    empty = {"pn": "dgc_status", "pt": 1, "pch": []}
    client = DaikinClient("http://unit")
    monkeypatch.setattr(client, "read", _read_returning({ADDR_STATUS: empty}))

    status = client.air_status()

    assert status.power is None
    assert status.humidify is None
    assert status.course is None
    assert status.humidity_setting is None
    assert status.temperature_c is None
    assert status.pm25_raw is None


INFO_PC = {
    "pn": "adp_i",
    "pt": 1,
    "pch": [
        {"pn": "mac", "pv": "00005E005301", "md": {"pt": "s"}},
        {"pn": "ver", "pv": "3_15_0", "md": {"pt": "s"}},
    ],
}
DEVICE_PC = {
    "pn": "adp_d",
    "pt": 1,
    "pch": [
        {"pn": "name", "pv": "MCK706A", "md": {"pt": "s"}},
        {"pn": "led", "pv": 1, "md": {"pt": "i"}},
        {
            "pn": "timz",
            "pt": 1,
            "pch": [{"pn": "tmdf", "pv": 540, "md": {"pt": "i"}}],
        },
    ],
}
RUNTIME_PC = {
    "pn": "adp_r",
    "pt": 1,
    "pch": [
        {
            "pn": "wlan_info",
            "pt": 1,
            "pch": [
                {"pn": "ssid", "pv": "Home", "md": {"pt": "s"}},
                {"pn": "rssi", "pv": -46, "md": {"pt": "i"}},
            ],
        },
    ],
}
DEVICE_TYPE_PC = {
    "pn": "dev_i",
    "pt": 1,
    "pch": [{"pn": "type", "pv": "1D", "md": {"pt": "s"}}],
}


def test_device_info_maps_fields(monkeypatch):
    client = DaikinClient("http://unit")
    monkeypatch.setattr(
        client,
        "read",
        _read_returning(
            {
                ADDR_INFO: INFO_PC,
                ADDR_DEVICE: DEVICE_PC,
                ADDR_ADAPTER_RUNTIME: RUNTIME_PC,
                ADDR_DEVICE_TYPE: DEVICE_TYPE_PC,
            }
        ),
    )

    info = client.device_info()

    assert info.name == "MCK706A"
    assert info.device_type == "1D"
    assert info.mac == "00005E005301"
    assert info.firmware == "3_15_0"
    assert info.wlan_ssid == "Home"
    assert info.wlan_rssi_dbm == -46
    assert info.led is True
    assert info.timezone_offset_min == 540
    assert info.region is None  # absent in the sample


def test_set_power_builds_write(monkeypatch):
    client = DaikinClient("http://unit")
    captured: dict = {}

    def fake_write(to, entity_path, pv):
        captured.update(to=to, entity_path=entity_path, pv=pv)
        return {"rsc": 2000}

    monkeypatch.setattr(client, "write", fake_write)

    client.set_power(True)
    assert captured["to"] == ADDR_STATUS
    assert captured["entity_path"] == ["e_1002", "e_A002", "p_01"]
    assert captured["pv"] == "01"

    client.set_power(False)
    assert captured["pv"] == "00"
