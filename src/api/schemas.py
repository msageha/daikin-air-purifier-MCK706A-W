import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeviceInfo(BaseModel):
    name: str | None = Field(
        default=None,
        description="User-assigned device name (edge.adp_d 'name')",
        examples=["MCK706A"],
    )
    mac: str | None = Field(
        default=None,
        description="Wi-Fi adapter MAC address (edge.adp_i 'mac')",
        examples=["00005E005301"],
    )
    firmware: str | None = Field(
        default=None,
        description="Adapter firmware version (edge.adp_i 'ver')",
        examples=["3_15_0"],
    )
    revision: str | None = Field(
        default=None,
        description="Firmware revision (edge.adp_i 'rev')",
    )
    region: str | None = Field(
        default=None,
        description="Region / locale code (edge.adp_i 'reg')",
    )
    ssid: str | None = Field(
        default=None,
        description="Connected Wi-Fi SSID (edge.adp_i 'ssid')",
    )
    api_ver: str | None = Field(
        default=None,
        description="dsiot API version exposed by the unit (edge.adp_i 'api_ver')",
        examples=["2_2"],
    )
    led: bool | None = Field(
        default=None,
        description="Status LED enabled (edge.adp_d 'led')",
    )
    timezone_offset_min: int | None = Field(
        default=None,
        description="Timezone offset from UTC in minutes (edge.adp_d 'timz/tmdf')",
        examples=[540],
    )


class AirStatus(BaseModel):
    power: bool | None = Field(
        default=None, description="Purifier on/off", examples=[True]
    )
    temperature_c: float | None = Field(
        default=None, description="Room temp (degC)", examples=[24.5]
    )
    humidity_pct: int | None = Field(
        default=None, description="Relative humidity (%)", ge=0, le=100, examples=[45]
    )
    mode: int | None = Field(
        default=None, description="Operation mode (raw 0..5)", ge=0, le=5, examples=[0]
    )
    fan_rate: int | None = Field(
        default=None, description="Airflow level (raw 0..7)", ge=0, le=7, examples=[3]
    )
    monitors: dict[str, int | None] = Field(
        default_factory=dict,
        description="Decoded air-quality monitor values (units not yet mapped)",
    )


class PowerRequest(BaseModel):
    on: bool = Field(
        description="True to turn the purifier on, False to turn it off",
        examples=[True],
    )


_HEX_RE = re.compile(r"^([0-9a-fA-F]{2})+$")
_ENTITY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _validate_dsiot_address(
    value: str, *, must_reference_container: bool = False
) -> str:
    if not value.startswith("/dsiot/") or ".." in value or "://" in value:
        raise ValueError(f"invalid dsiot address: {value!r}")
    if must_reference_container and "." not in value.rsplit("/", 1)[-1]:
        raise ValueError(
            "address must reference a container, e.g. '...adr_0100.dgc_status'"
        )
    return value


class ReadRequest(BaseModel):
    targets: list[str] = Field(
        description="dsiot addresses to read",
        examples=[["/dsiot/edge/adr_0100.dgc_status", "/dsiot/edge.adp_i"]],
    )

    @field_validator("targets")
    @classmethod
    def _validate_targets(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("targets must not be empty")
        for t in v:
            _validate_dsiot_address(t)
        return v


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str = Field(
        description="dsiot address",
        examples=["/dsiot/edge/adr_0100.dgc_status"],
    )
    entity_path: list[str] = Field(
        description="Property name chain to the leaf",
        examples=[["e_1002", "e_A002", "p_01"]],
    )
    pv: str = Field(description="Little-endian hex value", examples=["01", "00"])
    confirm: bool = Field(default=False, description="Must be true to write")

    @field_validator("to")
    @classmethod
    def _validate_to(cls, v: str) -> str:
        return _validate_dsiot_address(v, must_reference_container=True)

    @field_validator("entity_path")
    @classmethod
    def _validate_entity_path(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("entity_path must not be empty")
        for seg in v:
            if not _ENTITY_SEGMENT_RE.fullmatch(seg):
                raise ValueError(f"invalid entity_path segment: {seg!r}")
        return v

    @field_validator("pv")
    @classmethod
    def _validate_pv(cls, v: str) -> str:
        if not _HEX_RE.fullmatch(v):
            raise ValueError("pv must be an even-length hex string, e.g. '01'")
        return v


class LeafValue(BaseModel):
    model_config = ConfigDict(extra="allow")

    pv: Any = Field(
        default=None,
        description="Raw dsiot property value (little-endian hex string, int, or str)",
        examples=["01"],
    )
    value: Any = Field(
        default=None,
        description="Best-effort decoded value (hex decoded to int when type is 'b')",
        examples=[1],
    )
    type: str | None = Field(
        default=None,
        description="dsiot property type: 'b' (hex binary), 'i' (int), 's' (string)",
        examples=["b"],
    )
    min: str | None = Field(
        default=None,
        description="Lower bound advertised by the device (md 'mi'), if any",
    )
    max: str | None = Field(
        default=None,
        description="Upper bound advertised by the device (md 'mx'), if any",
    )
    ascii: str | None = Field(
        default=None,
        description="ASCII rendering of a hex 'pv' when it looks like text",
    )
