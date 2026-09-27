from daikin.models import AirStatus, DeviceInfo


def test_device_info_defaults_optional():
    info = DeviceInfo.model_validate({"name": "MCK706A", "firmware": "3_15_0"})
    assert info.name == "MCK706A"
    assert info.mac is None


def test_air_status_roundtrip():
    status = AirStatus.model_validate(
        {
            "power": True,
            "temperature_c": 24.0,
            "humidity_pct": 65,
            "mode": 2,
            "fan_rate": 2,
            "monitors": {"pm_a": 660, "pm_b": None},
        }
    )
    assert status.power is True
    assert status.temperature_c == 24.0
    assert status.monitors["pm_a"] == 660
