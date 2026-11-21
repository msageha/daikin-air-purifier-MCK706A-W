"""API の request モデル。応答モデルは daikin.models にある。"""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

from daikin import Course, FanSpeed, HumiditySetting


def _validate_dsiot_address(value: str) -> str:
    if not value.startswith("/dsiot/") or ".." in value or "://" in value:
        raise ValueError(f"invalid dsiot address: {value!r}")
    # JSON の構文は孤立した surrogate (U+D800 など) も通すが、UTF-8 で表せない文字列は本体へ送らない。
    try:
        value.encode()
    except UnicodeEncodeError as err:
        raise ValueError(f"invalid dsiot address: {value!r}") from err
    return value


def _require_container(value: str) -> str:
    if "." not in value.rsplit("/", 1)[-1]:
        raise ValueError(
            "address must reference a container, e.g. '...adr_0100.dgc_status'"
        )
    return value


def _require_bool(value: object) -> object:
    # Literal[True] は strict でも、True と等しい 1 や 1.0 を受け付けるので、型を先に確かめる。
    if not isinstance(value, bool):
        raise ValueError("confirm must be the JSON true")  # noqa: TRY004 - pydantic の検証エラーにするため ValueError で送出する
    return value


type DsiotAddress = Annotated[str, AfterValidator(_validate_dsiot_address)]
type ContainerAddress = Annotated[DsiotAddress, AfterValidator(_require_container)]
type EntitySegment = Annotated[str, Field(pattern=r"^[A-Za-z0-9_]+$")]
type HexValue = Annotated[str, Field(pattern=r"^([0-9a-fA-F]{2})+$")]


class PowerRequest(BaseModel):
    on: bool = Field(description="true で運転開始、false で停止", examples=[True])


class HumidifyRequest(BaseModel):
    on: bool = Field(
        description="true で加湿 + 空気清浄、false で空気清浄のみ", examples=[True]
    )


class CourseRequest(BaseModel):
    course: Course = Field(
        description="現在の運転切替側に設定するコース", examples=[Course.POLLEN]
    )


class FanSpeedRequest(BaseModel):
    fan_speed: FanSpeed = Field(
        description="手動コースの風量", examples=[FanSpeed.TURBO]
    )


class HumiditySettingRequest(BaseModel):
    humidity_setting: HumiditySetting = Field(
        description="加湿側のコースに対する湿度設定",
        examples=[HumiditySetting.STANDARD],
    )


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
    confirm: Annotated[Literal[True], BeforeValidator(_require_bool)] = Field(
        description="誤操作防止。JSON の true 以外は受け付けない"
    )
