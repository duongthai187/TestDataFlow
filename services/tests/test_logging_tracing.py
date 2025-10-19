import logging

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from services.common import ServiceSettings, build_app, configure_logging
from services.common.tracing import _INSTRUMENTED_APPS, configure_tracing


@pytest.mark.usefixtures("caplog")
class TestTracingInstrumentation:
    def test_tracing_sets_provider_once(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = ServiceSettings(
            enable_tracing=True,
            enable_metrics=False,
            app_name="Tracing Test Service",
        )
        configure_logging(settings)
        caplog.set_level(logging.WARNING)
        before = len(_INSTRUMENTED_APPS)
        app = build_app(settings)
        after_first = len(_INSTRUMENTED_APPS)
        assert after_first == before + 1
        configure_tracing(app, settings)
        after_second = len(_INSTRUMENTED_APPS)
        assert after_second == after_first
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)

    def test_logging_injects_trace_identifiers(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = ServiceSettings(
            enable_tracing=True,
            enable_metrics=False,
            app_name="Logging Trace Test",
        )
        configure_logging(settings)
        build_app(settings)
        caplog.clear()
        tracer = trace.get_tracer(__name__)
        logger = logging.getLogger("trace-test")
        with caplog.at_level(logging.INFO):
            logger.info("outside span")
            outside_record = next(
                record for record in caplog.records if record.message == "outside span"
            )
            assert getattr(outside_record, "trace_id", "-") == "-"
            assert getattr(outside_record, "span_id", "-") == "-"
            with tracer.start_as_current_span("span"):
                logger.info("inside span")
        inside_record = next(record for record in caplog.records if record.message == "inside span")
        trace_id = getattr(inside_record, "trace_id", "-")
        span_id = getattr(inside_record, "span_id", "-")
        assert trace_id != "-"
        assert span_id != "-"
        assert len(trace_id) == 32
        assert len(span_id) == 16
