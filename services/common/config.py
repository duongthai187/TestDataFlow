from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_APP_NAME = "ecommerce-service"


class ServiceSettings(BaseSettings):
    """Base settings shared by all FastAPI services."""

    app_name: str = Field(default=DEFAULT_APP_NAME)
    environment: Literal["local", "dev", "staging", "prod"] = Field(default="local")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    service_host: str = Field(default="0.0.0.0")
    service_port: int = Field(default=8000)
    enable_metrics: bool = Field(default=True)
    enable_tracing: bool = Field(default=False)
    database_url: str | None = Field(default=None)
    redis_url: str | None = Field(default=None)
    kafka_bootstrap_servers: str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"), env_prefix="SERVICE_", extra="ignore"
    )


@lru_cache
def get_settings() -> ServiceSettings:
    """Return cached service settings."""

    return ServiceSettings()
