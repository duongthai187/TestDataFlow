import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.common import ServiceSettings, create_engine, dispose_engines
from services.fulfillment_service.app.main import create_app
from services.fulfillment_service.app.models import Base


def _run(coro):
    return asyncio.run(coro)


async def _prepare_app(tmp_path) -> FastAPI:
    db_file = tmp_path / "fulfillment.db"
    database_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = ServiceSettings(
        app_name="Fulfillment Service Test",
        enable_metrics=False,
        enable_tracing=False,
        database_url=database_url,
    )
    return create_app(settings)


def _shipment_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "orderId": 123,
        "fulfillmentCenterId": 10,
        "carrier": "DHL",
        "serviceLevel": "express",
        "estimatedDelivery": datetime(2025, 1, 5, tzinfo=timezone.utc).isoformat(),
        "tasks": [
            {"taskType": "pick", "assignedTo": "worker-1", "status": "ready"},
            {"taskType": "pack", "assignedTo": "worker-2"},
        ],
    }
    payload.update(overrides)
    return payload


def test_create_get_and_list_shipments(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post("/fulfillment/shipments", json=_shipment_payload())
                assert create_resp.status_code == 201
                shipment = create_resp.json()
                assert shipment["status"] == "pending"
                assert len(shipment["tasks"]) == 2
                shipment_id = shipment["id"]

                get_resp = await client.get(f"/fulfillment/shipments/{shipment_id}")
                assert get_resp.status_code == 200
                assert get_resp.json()["id"] == shipment_id

                list_resp = await client.get("/fulfillment/shipments", params={"orderId": 123})
                assert list_resp.status_code == 200
                data = list_resp.json()
                assert data["total"] == 1
                assert data["items"][0]["orderId"] == 123

    _run(body())
    _run(dispose_engines())


def test_status_transitions_and_events(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                shipment_id = (
                    await client.post("/fulfillment/shipments", json=_shipment_payload(orderId=222))
                ).json()["id"]

                packed = await client.post(
                    f"/fulfillment/shipments/{shipment_id}/status",
                    json={"status": "packed", "description": "boxed"},
                )
                assert packed.status_code == 200
                assert packed.json()["status"] == "packed"

                shipped = await client.post(
                    f"/fulfillment/shipments/{shipment_id}/status",
                    json={"status": "shipped", "trackingNumber": "TRACK-XYZ"},
                )
                assert shipped.status_code == 200
                shipped_body = shipped.json()
                assert shipped_body["status"] == "shipped"
                assert shipped_body["trackingNumber"] == "TRACK-XYZ"
                assert shipped_body["shippedAt"] is not None

                delivered = await client.post(
                    f"/fulfillment/shipments/{shipment_id}/status",
                    json={"status": "delivered"},
                )
                assert delivered.status_code == 200
                assert delivered.json()["deliveredAt"] is not None

                events = await client.get(f"/fulfillment/shipments/{shipment_id}/events")
                assert events.status_code == 200
                event_types = [entry["type"] for entry in events.json()]
                assert event_types == ["created", "status.packed", "status.shipped", "status.delivered"]

    _run(body())
    _run(dispose_engines())


def test_track_shipment(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/fulfillment/shipments", json=_shipment_payload(orderId=333))
                shipment = created.json()
                shipment_id = shipment["id"]

                shipped = await client.post(
                    f"/fulfillment/shipments/{shipment_id}/status",
                    json={"status": "packed"},
                )
                assert shipped.status_code == 200
                tracking = shipped.json()["trackingNumber"]

                await client.post(
                    f"/fulfillment/shipments/{shipment_id}/status",
                    json={"status": "shipped"},
                )

                track_resp = await client.get(f"/fulfillment/track/{tracking}")
                assert track_resp.status_code == 200
                body = track_resp.json()
                assert body["shipment"]["id"] == shipment_id
                assert any(event["type"] == "status.shipped" for event in body["events"])

    _run(body())
    _run(dispose_engines())


def test_create_return_request(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                shipment_id = (
                    await client.post("/fulfillment/shipments", json=_shipment_payload(orderId=444))
                ).json()["id"]

                return_resp = await client.post(
                    "/fulfillment/returns",
                    json={"orderId": 444, "shipmentId": shipment_id, "reason": "damaged"},
                )
                assert return_resp.status_code == 201
                return_id = return_resp.json()["id"]
                assert return_resp.json()["authorizationCode"]

                get_resp = await client.get(f"/fulfillment/returns/{return_id}")
                assert get_resp.status_code == 200
                assert get_resp.json()["id"] == return_id

                events = await client.get(f"/fulfillment/shipments/{shipment_id}/events")
                types = [entry["type"] for entry in events.json()]
                assert "return.created" in types

    _run(body())
    _run(dispose_engines())


def test_delete_shipment(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                shipment_id = (
                    await client.post("/fulfillment/shipments", json=_shipment_payload(orderId=555))
                ).json()["id"]

                delete_resp = await client.delete(f"/fulfillment/shipments/{shipment_id}")
                assert delete_resp.status_code == 204

                missing = await client.get(f"/fulfillment/shipments/{shipment_id}")
                assert missing.status_code == 404

    _run(body())
    _run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
