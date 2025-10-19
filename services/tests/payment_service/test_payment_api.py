import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.common import ServiceSettings, create_engine, dispose_engines
from services.payment_service.app.main import create_app
from services.payment_service.app.models import Base


def _run(coro):
    return asyncio.run(coro)


async def _prepare_app(tmp_path) -> FastAPI:
    db_file = tmp_path / "payments.db"
    database_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = ServiceSettings(
        app_name="Payment Service Test",
        enable_metrics=False,
        enable_tracing=False,
        database_url=database_url,
    )
    return create_app(settings)


def _payment_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "customerId": 1,
        "orderId": 100,
        "amount": "25.75",
        "currency": "usd",
        "paymentMethod": "card",
    }
    payload.update(overrides)
    return payload


def test_create_and_get_payment(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post("/payments", json=_payment_payload())
                assert create_resp.status_code == 201
                created = create_resp.json()
                assert created["customerId"] == 1
                assert created["orderId"] == 100
                assert created["amount"] == "25.75"
                assert created["status"] == "pending"
                payment_id = created["id"]

                get_resp = await client.get(f"/payments/{payment_id}")
                assert get_resp.status_code == 200
                assert get_resp.json()["id"] == payment_id

    _run(body())
    _run(dispose_engines())


def test_list_payments_and_filters(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/payments", json=_payment_payload(orderId=200, customerId=2))
                first = await client.post("/payments", json=_payment_payload())
                payment_id = first.json()["id"]

                await client.patch(
                    f"/payments/{payment_id}/status",
                    json={"status": "authorized"},
                )

                list_all = await client.get("/payments")
                assert list_all.status_code == 200
                assert list_all.json()["total"] == 2

                list_filtered = await client.get("/payments", params={"customerId": 1, "status": "authorized"})
                body = list_filtered.json()
                assert body["total"] == 1
                assert body["items"][0]["status"] == "authorized"

    _run(body())
    _run(dispose_engines())


def test_capture_and_refund_flow(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/payments", json=_payment_payload())
                payment_id = created.json()["id"]

                capture = await client.post(f"/payments/{payment_id}/capture")
                assert capture.status_code == 200
                assert capture.json()["status"] == "captured"

                refund = await client.post(f"/payments/{payment_id}/refund", json={})
                assert refund.status_code == 200
                assert refund.json()["status"] == "refunded"

                events = await client.get(f"/payments/{payment_id}/events")
                event_types = [entry["type"] for entry in events.json()]
                assert event_types.count("status_changed") == 2
                assert "payment_captured" in event_types
                assert "payment_refunded" in event_types

    _run(body())
    _run(dispose_engines())


def test_provider_reference_and_delete(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/payments", json=_payment_payload(providerReference=None))
                payment_id = created.json()["id"]

                update = await client.patch(
                    f"/payments/{payment_id}/provider",
                    json={"providerReference": "ref-123"},
                )
                assert update.status_code == 200
                assert update.json()["providerReference"] == "ref-123"

                delete_resp = await client.delete(f"/payments/{payment_id}")
                assert delete_resp.status_code == 204

                missing = await client.get(f"/payments/{payment_id}")
                assert missing.status_code == 404

    _run(body())
    _run(dispose_engines())


def test_missing_payment_returns_404(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                missing = await client.get("/payments/999")
                assert missing.status_code == 404

                capture = await client.post("/payments/999/capture")
                assert capture.status_code == 404

                refund = await client.post("/payments/999/refund", json={})
                assert refund.status_code == 404

    _run(body())
    _run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
