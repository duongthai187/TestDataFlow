import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.common import ServiceSettings, create_engine, dispose_engines
from services.order_service.app.main import create_app
from services.order_service.app.models import Base


def _run(coro):
    return asyncio.run(coro)


async def _prepare_app(tmp_path) -> FastAPI:
    db_file = tmp_path / "orders.db"
    database_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = ServiceSettings(
        app_name="Order Service Test",
        enable_metrics=False,
        enable_tracing=False,
        database_url=database_url,
    )
    return create_app(settings)


def _order_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "customerId": 1,
        "currency": "USD",
        "items": [
            {
                "sku": "SKU-1",
                "name": "Sample Product",
                "quantity": 2,
                "unitPrice": "10.00",
                "discountAmount": "0.00",
                "taxAmount": "0.50",
            },
            {
                "sku": "SKU-2",
                "name": "Second Product",
                "quantity": 1,
                "unitPrice": "5.50",
                "discountAmount": "0.50",
                "taxAmount": "0.25",
            },
        ],
        "shippingTotal": "5.00",
        "taxTotal": "1.25",
        "discountTotal": "1.00",
    }
    payload.update(overrides)
    return payload


def test_create_and_list_orders(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post("/orders", json=_order_payload())
                assert create_resp.status_code == 201
                created = create_resp.json()
                assert created["customerId"] == 1
                assert created["subtotal"] == "25.00"
                assert created["grandTotal"] == "30.25"
                assert len(created["items"]) == 2

                list_resp = await client.get("/orders")
                assert list_resp.status_code == 200
                listing = list_resp.json()
                assert listing["total"] == 1
                assert listing["items"][0]["customerId"] == 1

    _run(body())
    _run(dispose_engines())


def test_get_order_and_not_found(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                missing = await client.get("/orders/999")
                assert missing.status_code == 404

                create_resp = await client.post("/orders", json=_order_payload())
                order_id = create_resp.json()["id"]

                get_resp = await client.get(f"/orders/{order_id}")
                assert get_resp.status_code == 200
                assert get_resp.json()["id"] == order_id

    _run(body())
    _run(dispose_engines())


def test_update_status_and_events(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post("/orders", json=_order_payload())
                order_id = create_resp.json()["id"]

                update_resp = await client.patch(
                    f"/orders/{order_id}/status",
                    json={"status": "shipped"},
                )
                assert update_resp.status_code == 200
                assert update_resp.json()["status"] == "shipped"

                events_resp = await client.get(f"/orders/{order_id}/events")
                assert events_resp.status_code == 200
                events = events_resp.json()
                assert len(events) == 1
                assert events[0]["type"] == "status_changed"
                assert events[0]["payload"] == "shipped"

    _run(body())
    _run(dispose_engines())


def test_capture_payment_and_delete(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post("/orders", json=_order_payload())
                order_id = create_resp.json()["id"]

                await client.patch(
                    f"/orders/{order_id}/status",
                    json={"status": "processing"},
                )

                capture_resp = await client.post(f"/orders/{order_id}/payments/capture")
                assert capture_resp.status_code == 200
                captured = capture_resp.json()
                assert captured["isPaid"] is True

                events_resp = await client.get(f"/orders/{order_id}/events")
                events = events_resp.json()
                assert len(events) == 2
                types = {event["type"] for event in events}
                assert types == {"status_changed", "payment_captured"}

                delete_resp = await client.delete(f"/orders/{order_id}")
                assert delete_resp.status_code == 204

                get_resp = await client.get(f"/orders/{order_id}")
                assert get_resp.status_code == 404

    _run(body())
    _run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
