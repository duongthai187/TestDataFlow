import logging

from fastapi import FastAPI

from .config import ServiceSettings


def configure_tracing(app: FastAPI, settings: ServiceSettings) -> None:
    """Stub for wiring tracing provider when enabled."""

    if not settings.enable_tracing:
        return

    # Placeholder for OpenTelemetry provider wiring; to be completed in observability wave.
    logging.getLogger(settings.app_name).warning(
        "Tracing is enabled but no tracer provider is configured yet."
    )
