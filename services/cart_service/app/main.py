from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.common import (
    DEFAULT_APP_NAME,
    ServiceSettings,
    build_app,
    configure_logging,
    dispose_engines,
    get_session_factory,
    resolve_database_url,
)

from .api.carts import router as carts_router
from .api.health import router as health_router

SERVICE_NAME = "Cart Service"
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./cart_service.db"


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    """Create the Cart Service FastAPI application."""

    resolved_settings = settings or ServiceSettings()
    if resolved_settings.app_name == DEFAULT_APP_NAME:
        resolved_settings = resolved_settings.model_copy(update={"app_name": SERVICE_NAME})
    configure_logging(resolved_settings)
    database_url = resolve_database_url(resolved_settings, DEFAULT_DATABASE_URL)
    session_factory = get_session_factory(database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.session_factory = session_factory
        try:
            yield
        finally:
            await dispose_engines()

    app = build_app(resolved_settings, lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(carts_router)
    return app


app = create_app()
