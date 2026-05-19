from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Carmencita Smart System", alias="APP_NAME")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
        alias="CORS_ORIGINS",
    )
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:password@localhost:5432/carmencita_db",
        alias="DATABASE_URL",
    )

    # Configuracion SUNAT / Lycet
    sunat_env: Literal["mock", "beta", "production"] = Field(default="mock", alias="SUNAT_ENV")
    sunat_provider: str = Field(default="lycet", alias="SUNAT_PROVIDER")
    sunat_allow_real_emission: bool = Field(default=False, alias="SUNAT_ALLOW_REAL_EMISSION")
    lycet_api_url: str = Field(default="http://localhost:8001", alias="LYCET_API_URL")
    lycet_client_token: str = Field(default="123456", alias="LYCET_CLIENT_TOKEN")

    # Configuracion RENIEC y pagos
    reniec_api_token: Optional[str] = Field(default=None, alias="RENIEC_API_TOKEN")
    reniec_api_url: Optional[str] = Field(default=None, alias="RENIEC_API_URL")
    mercadopago_access_token: Optional[str] = Field(default=None, alias="MERCADOPAGO_ACCESS_TOKEN")
    mercadopago_public_key: Optional[str] = Field(default=None, alias="MERCADOPAGO_PUBLIC_KEY")

    # Seguridad interna
    secret_key: str = Field(default="change_me", alias="SECRET_KEY")
    algorithm: Literal["HS256"] = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    default_admin_username: str = Field(default="admin", alias="DEFAULT_ADMIN_USERNAME")
    default_admin_email: str = Field(default="admin@carmencita.com", alias="DEFAULT_ADMIN_EMAIL")
    default_admin_password: str = Field(default="admin123", alias="DEFAULT_ADMIN_PASSWORD")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def production_emission_blocked(self) -> bool:
        return self.sunat_env == "production" and not self.sunat_allow_real_emission


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Exportaciones de compatibilidad para modulos que aun importan constantes directamente.
RENIEC_API_TOKEN = settings.reniec_api_token
RENIEC_API_URL = settings.reniec_api_url
MERCADOPAGO_ACCESS_TOKEN = settings.mercadopago_access_token
MERCADOPAGO_PUBLIC_KEY = settings.mercadopago_public_key
