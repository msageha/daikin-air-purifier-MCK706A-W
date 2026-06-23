from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # The MCK706A local dsiot API has no authentication: anyone on the LAN can
    # read/write it. Only the device address and a request timeout are needed.
    # daikin_host is required: startup fails with a ValidationError if it is not
    # provided via .env (or an environment variable).
    daikin_host: str
    timeout: int = 10


@lru_cache
def get_settings() -> Settings:
    # daikin_host has no default; pydantic-settings populates it from the
    # environment / .env at runtime, which the static checker cannot see.
    return Settings()  # ty: ignore[missing-argument]
