from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    daikin_host: HttpUrl = Field(
        description="空気清浄機の URL (例: http://192.168.1.100)"
    )
    timeout: int = Field(
        default=10, gt=0, description="本体への HTTP タイムアウト (秒)"
    )


# pyright は pydantic-settings が環境変数から必須の値を埋めることを知らないので、引数の不足を誤検知する。
settings = Settings()  # pyright: ignore[reportCallIssue]
