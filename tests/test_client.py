import pytest

from daikin.client import ADDR_DEVICE, ADDR_INFO, ADDR_STATUS, DaikinClient

pytestmark = pytest.mark.unit


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
                        {"pn": "p_3F", "pv": "02", "md": {"pt": "b"}},
                    ],
                },
                {
                    "pn": "e_3007",
                    "pt": 1,
                    "pch": [
                        {"pn": "p_32", "pv": "03", "md": {"pt": "b"}},
                        {"pn": "p_3A", "pv": "1400", "md": {"pt": "b"}},
                        {"pn": "p_3B", "pv": "00", "md": {"pt": "b"}},
                    ],
                },
                {
                    "pn": "e_205E",
                    "pt": 1,
                    "pch": [
                        {"pn": "p_01", "pv": "940200", "md": {"pt": "b"}},
                        {"pn": "p_02", "pv": "00", "md": {"pt": "b"}},
                    ],
                },
            ],
        }
    ],
}


def test_air_status_decodes_known_fields(monkeypatch):
    client = DaikinClient("http://unit")
    monkeypatch.setattr(client, "read_one", lambda target: {"pc": STATUS_PC})

    status = client.air_status()

    assert status["power"] is True  # 0x01
    assert status["temperature_c"] == 24.0  # 0x0030 LE = 48, half-degrees
    assert status["humidity_pct"] == 65  # 0x41
    assert status["mode"] == 2
    assert status["fan_rate"] == 3
    assert status["monitors"]["monitor_a"] == 20  # 0x0014 LE
    assert status["monitors"]["pm_a"] == 660  # 0x000294 LE
    assert status["monitors"]["pm_b"] == 0


def test_air_status_missing_fields_become_none(monkeypatch):
    empty = {"pn": "dgc_status", "pt": 1, "pch": []}
    client = DaikinClient("http://unit")
    monkeypatch.setattr(client, "read_one", lambda target: {"pc": empty})

    status = client.air_status()

    assert status["power"] is None
    assert status["temperature_c"] is None
    assert status["monitors"]["pm_a"] is None


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
        {"pn": "led", "pv": "1", "md": {"pt": "b"}},
    ],
}


def test_device_info_maps_fields(monkeypatch):
    client = DaikinClient("http://unit")
    monkeypatch.setattr(
        client,
        "read",
        lambda targets: {ADDR_INFO: {"pc": INFO_PC}, ADDR_DEVICE: {"pc": DEVICE_PC}},
    )

    info = client.device_info()

    assert info["name"] == "MCK706A"
    assert info["mac"] == "00005E005301"
    assert info["firmware"] == "3_15_0"
    assert info["led"] is True
    assert info["region"] is None  # absent in the sample


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
