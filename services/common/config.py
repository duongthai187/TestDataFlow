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
    tracing_endpoint: str | None = Field(default=None)
    tracing_protocol: Literal["http/protobuf", "grpc"] = Field(default="http/protobuf")
    tracing_insecure: bool = Field(default=True)
    tracing_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    database_url: str | None = Field(default=None)
    redis_url: str | None = Field(default=None)
    kafka_bootstrap_servers: str | None = Field(default=None)
    order_service_url: str | None = Field(default=None)
    payment_service_url: str | None = Field(default=None)
    fulfillment_service_url: str | None = Field(default=None)
    timeline_cache_ttl_seconds: int = Field(default=300, ge=0)
    timeline_timeout_seconds: float = Field(default=2.0, gt=0.0)
    notification_rate_limit: int = Field(default=120, ge=1)
    notification_rate_window_seconds: int = Field(default=60, ge=1)
    support_attachment_dir: str = Field(default="./data/support/attachments")
    support_attachment_base_url: str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"), env_prefix="SERVICE_", extra="ignore"
    )


@lru_cache
def get_settings() -> ServiceSettings:
    """Return cached service settings."""

    return ServiceSettings()
