from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Carmencita Smart System", alias="APP_NAME")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")

    sunat_env: Literal["mock", "beta", "production"] = Field(default="mock", alias="SUNAT_ENV")
    sunat_provider: str = Field(default="lycet", alias="SUNAT_PROVIDER")
    sunat_allow_real_emission: bool = Field(default=False, alias="SUNAT_ALLOW_REAL_EMISSION")

    lycet_api_url: str = Field(default="http://localhost:8001", alias="LYCET_API_URL")
    lycet_client_token: str = Field(default="123456", alias="LYCET_CLIENT_TOKEN")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def production_emission_blocked(self) -> bool:
        return self.sunat_env == "production" and not self.sunat_allow_real_emission


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
