"""DaikinClient が返す復号済みの値。pydantic モデルなので FastAPI の応答にそのまま使える。"""

from typing import Any

from pydantic import BaseModel, Field


class DeviceInfo(BaseModel):
    """edge.adp_i (アダプタ情報) と edge.adp_d (ユーザー設定) から集めた機器情報。"""

    name: str | None = Field(
        default=None, description="ユーザーが付けた機器名", examples=["MCK706A"]
    )
    mac: str | None = Field(
        default=None,
        description="Wi-Fi アダプタの MAC アドレス",
        examples=["00005E005301"],
    )
    firmware: str | None = Field(
        default=None,
        description="アダプタのファームウェアバージョン",
        examples=["3_15_0"],
    )
    revision: str | None = Field(default=None, description="ファームウェアのリビジョン")
    region: str | None = Field(default=None, description="地域コード", examples=["jp"])
    ssid: str | None = Field(default=None, description="接続中の Wi-Fi SSID")
    api_ver: str | None = Field(
        default=None,
        description="本体が公開する dsiot API のバージョン",
        examples=["2_2"],
    )
    led: bool | None = Field(default=None, description="状態表示 LED が有効か")
    timezone_offset_min: int | None = Field(
        default=None,
        description="UTC からのタイムゾーンオフセット (分)",
        examples=[540],
    )


class AirStatus(BaseModel):
    """adr_0100.dgc_status から復号した運転状態とセンサー値。"""

    power: bool | None = Field(default=None, description="運転中か", examples=[True])
    temperature_c: float | None = Field(
        default=None, description="室温 (℃)", examples=[24.5]
    )
    humidity_pct: int | None = Field(
        default=None, description="相対湿度 (%)", examples=[45]
    )
    mode: int | None = Field(
        default=None,
        description="運転モード。生の値 (実機で観測した範囲は 0..5) で、ラベルは未確定",
        examples=[0],
    )
    fan_rate: int | None = Field(
        default=None,
        description="風量。生の値 (実機で観測した範囲は 0..7)",
        examples=[3],
    )
    monitors: dict[str, int | None] = Field(
        default_factory=dict,
        description="空気質モニターの復号値。単位・意味は未特定",
    )


class DecodedLeaf(BaseModel):
    """dsiot プロパティツリーの 1 リーフ。生の値と、可能なら復号した値を持つ。

    診断用なので、本体のメタ情報は型で弾かずそのまま返す。
    """

    pv: Any = Field(
        default=None,
        description="生の値 (リトルエンディアン 16 進文字列・int・str)",
        examples=["01"],
    )
    value: Any = Field(
        default=None,
        description="復号値。type が 'b' の 16 進を int にしたもの。それ以外と、16 進として読めないときは pv のまま",
        examples=[1],
    )
    type: Any = Field(
        default=None,
        description="値の型 (md.pt)。通常は 'b' (16 進バイト列) / 'i' (int) / 's' (文字列)",
        examples=["b"],
    )
    min: Any = Field(
        default=None, description="本体が示す下限 (md.mi)。通常は 16 進文字列"
    )
    max: Any = Field(
        default=None, description="本体が示す上限 (md.mx)。通常は 16 進文字列"
    )
    ascii: str | None = Field(
        default=None,
        description="16 進の pv を NUL 終端の ASCII として読めたときの文字列 (数値が偶然文字に見えることもある)",
    )
