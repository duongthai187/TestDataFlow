"""Shared utilities for ecommerce services."""

from .config import DEFAULT_APP_NAME, ServiceSettings, get_settings
from .instrumentation import build_app, instrument_app
from .logging import configure_logging
from .database import (
    create_engine,
    dispose_engines,
    get_session_factory,
    lifespan_session,
    resolve_database_url,
)
from .cache import close_redis_connections, get_redis_client, resolve_redis
from .kafka import KafkaConsumerStub, KafkaProducerStub

__all__ = [
    "ServiceSettings",
    "get_settings",
    "build_app",
    "instrument_app",
    "configure_logging",
    "DEFAULT_APP_NAME",
    "create_engine",
    "dispose_engines",
    "get_session_factory",
    "lifespan_session",
    "resolve_database_url",
    "get_redis_client",
    "resolve_redis",
    "close_redis_connections",
    "KafkaProducerStub",
    "KafkaConsumerStub",
]
