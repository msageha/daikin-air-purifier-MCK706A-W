from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env に他のキーがあっても起動が止まらないよう extra は無視する。
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    daikin_host: str = Field(description="空気清浄機の URL (例: http://192.168.1.100)")
    timeout: int = Field(default=10, description="本体への HTTP タイムアウト (秒)")


settings = Settings()
