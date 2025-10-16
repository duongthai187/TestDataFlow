from typing import Any, cast

from fastapi import FastAPI
# Allow running in environments without optional metrics dependency.
try:  # pragma: no cover - optional dependency handling
    from prometheus_fastapi_instrumentator import Instrumentator
except ModuleNotFoundError:  # pragma: no cover - executed only when optional dep missing
    Instrumentator = None  # type: ignore[assignment]

from .config import ServiceSettings
from .tracing import configure_tracing


def instrument_app(app: FastAPI, settings: ServiceSettings) -> None:
    """Attach metrics exporters when enabled."""

    if settings.enable_metrics and Instrumentator is not None:
        Instrumentator().instrument(app).expose(app)

    state = cast(Any, app.state)
    state.settings = settings


def build_app(settings: ServiceSettings, **extra_kwargs: Any) -> FastAPI:
    """Create a FastAPI instance with standard metadata and instrumentation."""

    app = FastAPI(title=settings.app_name, version="0.1.0", **extra_kwargs)
    instrument_app(app, settings)
    configure_tracing(app, settings)
    return app
