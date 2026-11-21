from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    daikin_host: str = Field(
        min_length=1, description="空気清浄機の URL (例: http://192.168.1.100)"
    )
    timeout: int = Field(default=10, description="本体への HTTP タイムアウト (秒)")


settings = Settings()
