"""API の request モデル。応答モデルは daikin.models にある。"""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _validate_dsiot_address(value: str) -> str:
    if not value.startswith("/dsiot/") or ".." in value or "://" in value:
        raise ValueError(f"invalid dsiot address: {value!r}")
    return value


def _require_container(value: str) -> str:
    if "." not in value.rsplit("/", 1)[-1]:
        raise ValueError(
            "address must reference a container, e.g. '...adr_0100.dgc_status'"
        )
    return value


DsiotAddress = Annotated[str, AfterValidator(_validate_dsiot_address)]
ContainerAddress = Annotated[DsiotAddress, AfterValidator(_require_container)]
EntitySegment = Annotated[str, Field(pattern=r"^[A-Za-z0-9_]+$")]
HexValue = Annotated[str, Field(pattern=r"^([0-9a-fA-F]{2})+$")]


class PowerRequest(BaseModel):
    on: bool = Field(description="true で運転開始、false で停止", examples=[True])


class ReadRequest(BaseModel):
    targets: list[DsiotAddress] = Field(
        min_length=1,
        description="読み取る dsiot アドレス",
        examples=[["/dsiot/edge/adr_0100.dgc_status", "/dsiot/edge.adp_i"]],
    )


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: ContainerAddress = Field(
        description="書き込み先のコンテナアドレス",
        examples=["/dsiot/edge/adr_0100.dgc_status"],
    )
    entity_path: list[EntitySegment] = Field(
        min_length=1,
        description="コンテナ直下からリーフまでのプロパティ名の並び",
        examples=[["e_1002", "e_A002", "p_01"]],
    )
    pv: HexValue = Field(
        description="書き込む値 (リトルエンディアン 16 進、偶数長)", examples=["01"]
    )
    confirm: Literal[True] = Field(description="誤操作防止。true 以外は受け付けない")
