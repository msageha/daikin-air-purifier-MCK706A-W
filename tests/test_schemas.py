import pytest
from pydantic import ValidationError

from api.schemas import (
    AirStatus,
    DeviceInfo,
    ReadRequest,
    WriteRequest,
)

pytestmark = pytest.mark.unit


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


def test_read_request_requires_dsiot_prefix():
    ok = ReadRequest.model_validate({"targets": ["/dsiot/edge.adp_i"]})
    assert ok.targets == ["/dsiot/edge.adp_i"]
    with pytest.raises(ValidationError):
        ReadRequest.model_validate({"targets": ["/etc/passwd"]})
    with pytest.raises(ValidationError):
        ReadRequest.model_validate({"targets": []})


def test_write_request_validation():
    ok = WriteRequest.model_validate(
        {
            "to": "/dsiot/edge/adr_0100.dgc_status",
            "entity_path": ["e_1002", "e_A002", "p_01"],
            "pv": "01",
            "confirm": True,
        }
    )
    assert ok.pv == "01"

    # odd-length hex
    with pytest.raises(ValidationError):
        WriteRequest.model_validate(
            {
                "to": "/dsiot/edge/adr_0100.dgc_status",
                "entity_path": ["e_1002"],
                "pv": "1",
            }
        )
    # 'to' without a container reference
    with pytest.raises(ValidationError):
        WriteRequest.model_validate(
            {
                "to": "/dsiot/edge/adr_0100",
                "entity_path": ["e_1002"],
                "pv": "01",
            }
        )
    # extra field rejected
    with pytest.raises(ValidationError):
        WriteRequest.model_validate(
            {
                "to": "/dsiot/edge/adr_0100.dgc_status",
                "entity_path": ["e_1002"],
                "pv": "01",
                "bogus": 1,
            }
        )
