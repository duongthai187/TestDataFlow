from fastapi import FastAPI

from services.common import DEFAULT_APP_NAME, ServiceSettings, build_app, configure_logging

from .api.health import router as health_router

SERVICE_NAME = "Order Service"


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    """Create the Order Service FastAPI application."""

    resolved_settings = settings or ServiceSettings()
    if resolved_settings.app_name == DEFAULT_APP_NAME:
        resolved_settings = resolved_settings.model_copy(update={"app_name": SERVICE_NAME})
    configure_logging(resolved_settings)
    app = build_app(resolved_settings)
    app.include_router(health_router)
    return app


app = create_app()
