from collections.abc import Callable
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.cart_service.app.main import create_app as create_cart_app
from services.catalog_service.app.main import create_app as create_catalog_app
from services.customer_service.app.main import create_app as create_customer_app
from services.fraud_service.app.main import create_app as create_fraud_app
from services.fulfillment_service.app.main import create_app as create_fulfillment_app
from services.inventory_service.app.main import create_app as create_inventory_app
from services.notification_service.app.main import create_app as create_notification_app
from services.order_service.app.main import create_app as create_order_app
from services.payment_service.app.main import create_app as create_payment_app
from services.pricing_service.app.main import create_app as create_pricing_app
from services.recommendation_service.app.main import create_app as create_recommendation_app
from services.review_service.app.main import create_app as create_review_app
from services.support_service.app.main import create_app as create_support_app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "app_factory",
    [
        create_cart_app,
        create_catalog_app,
        create_customer_app,
        create_fraud_app,
        create_fulfillment_app,
        create_inventory_app,
        create_notification_app,
        create_order_app,
        create_payment_app,
        create_pricing_app,
        create_recommendation_app,
        create_review_app,
        create_support_app,
    ],
)
async def test_health_endpoint_returns_ok(app_factory: Callable[[], FastAPI]) -> None:
    app = app_factory()

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
