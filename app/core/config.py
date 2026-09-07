from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


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
    db_user: Optional[str] = Field(default=None, alias="DB_USER")
    db_password: Optional[str] = Field(default=None, alias="DB_PASSWORD")
    db_name: Optional[str] = Field(default=None, alias="DB_NAME")
    instance_unix_socket: Optional[str] = Field(default=None, alias="INSTANCE_UNIX_SOCKET")
    db_pool_size: int = Field(default=2, ge=1, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=0, ge=0, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, ge=1, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=300, ge=1, alias="DB_POOL_RECYCLE")
    db_connect_timeout: int = Field(default=10, ge=1, alias="DB_CONNECT_TIMEOUT")
    auto_create_schema: bool = Field(default=True, alias="AUTO_CREATE_SCHEMA")

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
    default_admin_password: str = Field(default="admin123", alias="DEFAULT_ADMIN_PASSWORD")

    # Asistente Virtual / LLM — Groq
    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-20b", alias="GROQ_MODEL")
    assistant_llm_enabled: bool = Field(default=False, alias="ASSISTANT_LLM_ENABLED")

    # Búsqueda web (recojo externo: sedes de agencias). Provider por defecto: Serper
    # (https://serper.dev). Si no se configura la key, el asistente pide la dirección
    # exacta en lugar de buscar en internet.
    search_api_key: Optional[str] = Field(default=None, alias="SEARCH_API_KEY")
    search_api_url: str = Field(default="https://google.serper.dev/search", alias="SEARCH_API_URL")
    search_provider: str = Field(default="serper", alias="SEARCH_PROVIDER")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sqlalchemy_database_url(self) -> str | URL:
        if self.instance_unix_socket:
            missing = [
                name
                for name, value in (
                    ("DB_USER", self.db_user),
                    ("DB_PASSWORD", self.db_password),
                    ("DB_NAME", self.db_name),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "Cloud SQL socket configuration requires " + ", ".join(missing)
                )
            return URL.create(
                drivername="postgresql+psycopg2",
                username=self.db_user,
                password=self.db_password,
                host=self.instance_unix_socket,
                database=self.db_name,
            )

        value = self.database_url.strip()
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg2://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg2://", 1)
        return value

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
