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
    resolve_redis,
    close_redis_connections,
)
from services.common.kafka import KafkaConsumerStub, KafkaProducerStub

from .api.health import router as health_router
from .api.notifications import router as notifications_router
from .rate_limit import RateLimiter
from .events import NotificationEventPublisher
from .providers import InMemoryNotificationProvider
from .event_handlers import NotificationEventHandler

SERVICE_NAME = "Notification Service"
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./notification_service.db"


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    """Create the Notification Service FastAPI application."""

    resolved_settings = settings or ServiceSettings()
    if resolved_settings.app_name == DEFAULT_APP_NAME:
        resolved_settings = resolved_settings.model_copy(update={"app_name": SERVICE_NAME})
    configure_logging(resolved_settings)
    database_url = resolve_database_url(resolved_settings, DEFAULT_DATABASE_URL)
    session_factory = get_session_factory(database_url)

    redis_client = resolve_redis(resolved_settings)
    rate_limiter = RateLimiter(
        redis_client,
        limit=resolved_settings.notification_rate_limit,
        window_seconds=resolved_settings.notification_rate_window_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        kafka_producer: KafkaProducerStub | None = None
        event_publisher: NotificationEventPublisher | None = None
        notification_provider: InMemoryNotificationProvider | None = None
        event_consumer: KafkaConsumerStub | None = None
        event_handler: NotificationEventHandler | None = None
        app.state.session_factory = session_factory
        app.state.rate_limiter = rate_limiter
        try:
            kafka_producer = KafkaProducerStub(bootstrap_servers=resolved_settings.kafka_bootstrap_servers)
            await kafka_producer.connect()
            event_publisher = NotificationEventPublisher(kafka_producer)
            notification_provider = InMemoryNotificationProvider()
            app.state.event_publisher = event_publisher
            app.state.notification_provider = notification_provider
            app.state.kafka_producer = kafka_producer
            event_handler = NotificationEventHandler(
                session_factory,
                rate_limiter=rate_limiter,
                provider=notification_provider,
                event_publisher=event_publisher,
            )
            event_consumer = KafkaConsumerStub(
                [
                    "support.case.updated.v1",
                    "support.case.closed.v1",
                    "order.status.changed.v1",
                    "fulfillment.shipment.updated.v1",
                ],
                event_handler.handle,
            )
            await event_consumer.start()
            app.state.notification_event_consumer = event_consumer
            app.state.notification_event_handler = event_handler
            yield
        finally:
            app.state.session_factory = None  # type: ignore[assignment]
            app.state.rate_limiter = None  # type: ignore[assignment]
            app.state.event_publisher = None
            app.state.notification_provider = None
            app.state.kafka_producer = None
            app.state.notification_event_consumer = None
            app.state.notification_event_handler = None
            if event_consumer is not None:
                await event_consumer.stop()
            if kafka_producer is not None:
                await kafka_producer.close()
            await dispose_engines()
            if redis_client is not None:
                await close_redis_connections()

    app = build_app(resolved_settings, lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(notifications_router)
    return app


app = create_app()
