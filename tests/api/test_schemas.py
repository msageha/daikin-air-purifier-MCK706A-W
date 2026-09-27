import pytest
from pydantic import ValidationError

from api.schemas import ReadRequest, WriteRequest


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

    base = {
        "to": "/dsiot/edge/adr_0100.dgc_status",
        "entity_path": ["e_1002"],
        "pv": "01",
        "confirm": True,
    }
    # odd-length hex
    with pytest.raises(ValidationError):
        WriteRequest.model_validate({**base, "pv": "1"})
    # 'to' without a container reference
    with pytest.raises(ValidationError):
        WriteRequest.model_validate({**base, "to": "/dsiot/edge/adr_0100"})
    # extra field rejected
    with pytest.raises(ValidationError):
        WriteRequest.model_validate({**base, "bogus": 1})
