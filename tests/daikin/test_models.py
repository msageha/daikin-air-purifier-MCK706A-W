from daikin.models import AirStatus, Course, DeviceInfo, FanSpeed


def test_device_info_defaults_optional():
    info = DeviceInfo.model_validate({"name": "MCK706A", "firmware": "3_15_0"})
    assert info.name == "MCK706A"
    assert info.mac is None


def test_air_status_roundtrip():
    status = AirStatus.model_validate(
        {
            "power": True,
            "humidify": False,
            "course": "manual",
            "fan_speed": "turbo",
            "temperature_c": 24.0,
            "humidity_pct": 65,
            "pm25_level": 0,
            "error_code": "00-00",
        }
    )
    assert status.power is True
    assert status.course is Course.MANUAL
    assert status.fan_speed is FanSpeed.TURBO
    assert status.humidity_setting is None
    assert status.temperature_c == 24.0
    assert status.model_dump()["course"] == "manual"
