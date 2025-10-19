import logging
from typing import Literal

try:  # pragma: no cover - logging works without tracing dependency
    from opentelemetry import trace
except ModuleNotFoundError:  # pragma: no cover - executed when tracing libs missing
    trace = None  # type: ignore[assignment]

from .config import ServiceSettings


_TRACE_PLACEHOLDER = "-"
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | trace_id=%(trace_id)s span_id=%(span_id)s | %(message)s"


def _format_trace_id(value: int, length: int) -> str:
    return format(value, f"0{length}x")


class TraceContextFilter(logging.Filter):
    """Populate trace/span identifiers when OpenTelemetry is active."""

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - exercised in tests
        if trace is None:
            record.trace_id = _TRACE_PLACEHOLDER
            record.span_id = _TRACE_PLACEHOLDER
            return True

        span = trace.get_current_span()
        span_context = span.get_span_context() if span is not None else None
        if span_context is not None and span_context.is_valid:
            record.trace_id = _format_trace_id(span_context.trace_id, 32)
            record.span_id = _format_trace_id(span_context.span_id, 16)
        else:
            record.trace_id = _TRACE_PLACEHOLDER
            record.span_id = _TRACE_PLACEHOLDER
        return True


def configure_logging(settings: ServiceSettings) -> None:
    """Configure root logging level and format."""

    logging_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = settings.log_level
    logging.basicConfig(level=logging_level, format=_LOG_FORMAT)
    root_logger = logging.getLogger()
    existing_filter = next(
        (f for f in root_logger.filters if isinstance(f, TraceContextFilter)),
        None,
    )
    context_filter = existing_filter or TraceContextFilter()
    if existing_filter is None:
        root_logger.addFilter(context_filter)
    for handler in root_logger.handlers:
        if not any(isinstance(f, TraceContextFilter) for f in handler.filters):
            handler.addFilter(context_filter)
