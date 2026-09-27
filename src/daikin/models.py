"""DaikinClient が返す復号済みの値。pydantic モデルなので FastAPI の応答にそのまま使える。

コース・風量・湿度設定のラベルは公式 DAIKIN Smart App (GPFCjConvertValue /
strings.xml) の空気清浄機向け定義に合わせている。wire 値との対応は client.py が持つ。
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Course(StrEnum):
    """運転コース (アプリの「コース」)。定義順が dsiot の wire 値 (0 始まり)。"""

    SMART = "smart"
    MANUAL = "manual"
    AUTO_FAN = "auto_fan"
    ECONO = "econo"
    POLLEN = "pollen"
    MOIST = "moist"
    CIRCULATOR = "circulator"
    LAUNDRY_DRY = "laundry_dry"
    NIGHT_LAUNDRY_DRY = "night_laundry_dry"
    WATER_DEODORIZE = "water_deodorize"
    INTERNAL_DRY = "internal_dry"


class FanSpeed(StrEnum):
    """手動コースの風量。定義順が dsiot の wire 値 (0 始まり)。"""

    QUIET = "quiet"
    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"
    TURBO = "turbo"


class HumiditySetting(StrEnum):
    """加湿運転時の湿度設定。定義順が dsiot の wire 値 (0 始まり)。"""

    OFF = "off"
    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"
    CONTINUOUS = "continuous"


class DeviceInfo(BaseModel):
    """edge.adp_i / adp_d / adp_r / dev_i から集めた機器・アダプタ情報。"""

    name: str | None = Field(
        default=None, description="ユーザーが付けた機器名", examples=["MCK706A"]
    )
    device_type: str | None = Field(
        default=None,
        description="dsiot の機器種別コード (1D = 空気清浄機、RA = ルームエアコン)",
        examples=["1D"],
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
    ssid: str | None = Field(
        default=None,
        description="アダプタ自身がセットアップ用に出すアクセスポイントの SSID",
        examples=["DaikinAP12345"],
    )
    wlan_ssid: str | None = Field(
        default=None, description="アダプタが接続している Wi-Fi の SSID"
    )
    wlan_rssi_dbm: int | None = Field(
        default=None, description="接続中 Wi-Fi の受信強度 (dBm)", examples=[-46]
    )
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
    humidify: bool | None = Field(
        default=None,
        description="運転切替。true = 加湿 + 空気清浄、false = 空気清浄のみ",
        examples=[False],
    )
    course: Course | None = Field(
        default=None,
        description="現在の運転切替 (humidify) 側で選ばれているコース",
        examples=[Course.SMART],
    )
    fan_speed: FanSpeed | None = Field(
        default=None,
        description="手動コース (manual) のときに使われる風量。他のコースでは無視される設定値",
        examples=[FanSpeed.STANDARD],
    )
    humidity_setting: HumiditySetting | None = Field(
        default=None,
        description="加湿側 (humidify が true のときに使われる) コースに対する湿度設定。そのコースが smart / moist のときは自動なので None",
        examples=[HumiditySetting.LOW],
    )
    temperature_c: float | None = Field(
        default=None, description="室温 (℃)", examples=[24.5]
    )
    humidity_pct: int | None = Field(
        default=None, description="相対湿度 (%)", examples=[45]
    )
    pm25_level: int | None = Field(
        default=None, description="PM2.5 の汚れレベル (0 = きれい 〜 5)", examples=[0]
    )
    dust_level: int | None = Field(
        default=None, description="ホコリの汚れレベル (0 = きれい 〜 5)", examples=[0]
    )
    odor_level: int | None = Field(
        default=None, description="ニオイの強さレベル (0 = なし 〜 5)", examples=[0]
    )
    pm25_raw: int | None = Field(
        default=None,
        description="PM2.5 センサーの生値。アプリの履歴グラフの元値と推定され、単位は未特定",
    )
    dust_raw: int | None = Field(
        default=None,
        description="ホコリセンサーの生値。アプリの履歴グラフの元値と推定され、単位は未特定",
    )
    odor_raw: int | None = Field(
        default=None,
        description="ニオイセンサーの生値。アプリの履歴グラフの元値と推定され、単位は未特定",
    )
    water_supply_sign: bool | None = Field(
        default=None, description="給水サイン (加湿タンクが空)"
    )
    filter_drying: bool | None = Field(
        default=None, description="加湿フィルター乾燥運転中か"
    )
    deodorizing_filter_off_sign: bool | None = Field(
        default=None, description="脱臭フィルター外れサイン"
    )
    streamer_maintenance_sign: bool | None = Field(
        default=None, description="ストリーマユニットのお手入れサイン"
    )
    error_code: str | None = Field(
        default=None,
        description="本体のエラーコード。'00-00' は正常",
        examples=["00-00"],
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
        default=None,
        description="本体が示す上限 (md.mx)。通常は 16 進文字列。列挙型のプロパティでは対応値のビットマスク",
    )
    ascii: str | None = Field(
        default=None,
        description="16 進の pv を NUL 終端の ASCII として読めたときの文字列 (数値が偶然文字に見えることもある)",
    )
