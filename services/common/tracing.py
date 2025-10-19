import logging

from fastapi import FastAPI

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[attr-defined]
    OTLPSpanExporter as OTLPGrpcExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[attr-defined]
    OTLPSpanExporter as OTLPHttpExporter,
)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import TracerProvider as APITracerProvider

from .config import ServiceSettings

_LOGGER = logging.getLogger(__name__)
_INSTRUMENTED_APPS: set[int] = set()
_HTTPX_INSTRUMENTED = False


def _create_exporter(settings: ServiceSettings):
    if settings.tracing_endpoint is None:
        return None
    if settings.tracing_protocol == "grpc":
        return OTLPGrpcExporter(endpoint=settings.tracing_endpoint, insecure=settings.tracing_insecure)
    return OTLPHttpExporter(endpoint=settings.tracing_endpoint)


def _ensure_provider(settings: ServiceSettings) -> APITracerProvider:
    current_provider = trace.get_tracer_provider()
    if isinstance(current_provider, TracerProvider):
        return current_provider

    resource = Resource.create(
        {
            "service.name": settings.app_name,
            "deployment.environment": settings.environment,
        }
    )
    sampler = TraceIdRatioBased(settings.tracing_sample_rate)
    provider = TracerProvider(resource=resource, sampler=sampler)
    exporter = _create_exporter(settings)
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        _LOGGER.warning(
            "Tracing is enabled for %s but no OTLP endpoint is configured; spans will not be exported.",
            settings.app_name,
        )
    try:
        trace.set_tracer_provider(provider)
    except RuntimeError:  # pragma: no cover - occurs when provider already initialized elsewhere
        return trace.get_tracer_provider()
    return provider


def _instrument_httpx(provider: APITracerProvider) -> None:
    global _HTTPX_INSTRUMENTED
    if _HTTPX_INSTRUMENTED:
        return
    try:
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    except Exception as exc:  # pragma: no cover - defensive logging only
        _LOGGER.warning("Failed to instrument httpx for tracing: %s", exc)
    else:
        _HTTPX_INSTRUMENTED = True


def _instrument_app(app: FastAPI, provider: APITracerProvider) -> None:
    app_id = id(app)
    if app_id in _INSTRUMENTED_APPS:
        return
    FastAPIInstrumentor().instrument_app(app, tracer_provider=provider)
    _INSTRUMENTED_APPS.add(app_id)


def configure_tracing(app: FastAPI, settings: ServiceSettings) -> None:
    """Configure OpenTelemetry tracing when enabled in settings."""

    if not settings.enable_tracing:
        return

    provider = _ensure_provider(settings)
    _instrument_app(app, provider)
    _instrument_httpx(provider)
