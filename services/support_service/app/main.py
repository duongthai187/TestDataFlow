from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from httpx import AsyncClient

from services.common import (
    DEFAULT_APP_NAME,
    ServiceSettings,
    build_app,
    configure_logging,
    dispose_engines,
    get_session_factory,
    resolve_database_url,
    resolve_redis,
    close_redis_connections,
)
from services.common.kafka import KafkaConsumerStub, KafkaProducerStub

from .api.health import router as health_router
from .api.support import router as support_router
from .event_handlers import FulfillmentEventHandler
from .events import SupportEventPublisher
from .storage import LocalAttachmentStorage
from .timeline import TimelineAggregator

SERVICE_NAME = "Support Service"
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./support_service.db"


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    """Create the Support Service FastAPI application."""

    resolved_settings = settings or ServiceSettings()
    if resolved_settings.app_name == DEFAULT_APP_NAME:
        resolved_settings = resolved_settings.model_copy(update={"app_name": SERVICE_NAME})
    configure_logging(resolved_settings)
    database_url = resolve_database_url(resolved_settings, DEFAULT_DATABASE_URL)
    session_factory = get_session_factory(database_url)

    redis_client = resolve_redis(resolved_settings)
    attachment_storage = LocalAttachmentStorage(
        base_path=Path(resolved_settings.support_attachment_dir),
        base_url=resolved_settings.support_attachment_base_url,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        aggregator: TimelineAggregator | None = None
        http_client: AsyncClient | None = None
        kafka_producer: KafkaProducerStub | None = None
        event_publisher: SupportEventPublisher | None = None
        fulfillment_consumer: KafkaConsumerStub | None = None
        fulfillment_handler: FulfillmentEventHandler | None = None
        app.state.session_factory = session_factory
        app.state.attachment_storage = attachment_storage
        try:
            http_client = AsyncClient(timeout=resolved_settings.timeline_timeout_seconds)
            aggregator = TimelineAggregator(
                client=http_client,
                redis=redis_client,
                cache_ttl=resolved_settings.timeline_cache_ttl_seconds,
                order_base_url=resolved_settings.order_service_url,
                payment_base_url=resolved_settings.payment_service_url,
                fulfillment_base_url=resolved_settings.fulfillment_service_url,
            )
            app.state.timeline_aggregator = aggregator
            kafka_producer = KafkaProducerStub(bootstrap_servers=resolved_settings.kafka_bootstrap_servers)
            await kafka_producer.connect()
            event_publisher = SupportEventPublisher(kafka_producer)
            app.state.event_publisher = event_publisher
            fulfillment_handler = FulfillmentEventHandler(session_factory, aggregator, event_publisher)
            fulfillment_consumer = KafkaConsumerStub(
                ["fulfillment.shipment.updated.v1"],
                fulfillment_handler.handle,
            )
            await fulfillment_consumer.start()
            app.state.fulfillment_consumer = fulfillment_consumer
            app.state.fulfillment_handler = fulfillment_handler
            yield
        finally:
            app.state.session_factory = None  # type: ignore[assignment]
            app.state.timeline_aggregator = None
            app.state.attachment_storage = None
            app.state.event_publisher = None
            app.state.fulfillment_consumer = None
            app.state.fulfillment_handler = None
            if aggregator is not None:
                await aggregator.close()
            elif http_client is not None:
                await http_client.aclose()
            if kafka_producer is not None:
                await kafka_producer.close()
            if fulfillment_consumer is not None:
                await fulfillment_consumer.stop()
            await dispose_engines()
            if redis_client is not None:
                await close_redis_connections()
            await attachment_storage.close()

    app = build_app(resolved_settings, lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(support_router)
    return app


app = create_app()
