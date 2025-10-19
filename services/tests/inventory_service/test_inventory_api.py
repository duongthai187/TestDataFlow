import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.common import ServiceSettings, create_engine, dispose_engines
from services.inventory_service.app.main import create_app
from services.inventory_service.app.models import Base


def _run(coro):
    return asyncio.run(coro)


async def _prepare_app(tmp_path) -> FastAPI:
    db_file = tmp_path / "inventory.db"
    database_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = ServiceSettings(
        app_name="Inventory Service Test",
        enable_metrics=False,
        enable_tracing=False,
        database_url=database_url,
    )
    return create_app(settings)


def _inventory_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "sku": "SKU-1",
        "location": "WH-1",
        "quantityOnHand": 10,
        "safetyStock": 2,
    }
    payload.update(overrides)
    return payload


def test_create_and_get_inventory(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post("/inventory", json=_inventory_payload())
                assert create_resp.status_code == 201
                created = create_resp.json()
                assert created["available"] == 10 - created["quantityReserved"]
                item_id = created["id"]

                get_resp = await client.get(f"/inventory/{item_id}")
                assert get_resp.status_code == 200
                assert get_resp.json()["id"] == item_id

    _run(body())
    _run(dispose_engines())


def test_list_and_conflict(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/inventory", json=_inventory_payload(sku="SKU-2", location="WH-2"))
                create_resp = await client.post("/inventory", json=_inventory_payload())
                assert create_resp.status_code == 201

                conflict = await client.post("/inventory", json=_inventory_payload())
                assert conflict.status_code == 409

                list_resp = await client.get("/inventory", params={"sku": "SKU-1"})
                assert list_resp.status_code == 200
                body = list_resp.json()
                assert body["total"] == 1
                assert body["items"][0]["sku"] == "SKU-1"

    _run(body())
    _run(dispose_engines())


def test_adjust_and_restock(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/inventory", json=_inventory_payload(quantityOnHand=5))
                item_id = created.json()["id"]

                adjust = await client.patch(
                    f"/inventory/{item_id}",
                    json={"quantityOnHand": 8, "safetyStock": 1},
                )
                assert adjust.status_code == 200
                assert adjust.json()["quantityOnHand"] == 8
                assert adjust.json()["safetyStock"] == 1

                restock = await client.post(
                    f"/inventory/{item_id}/restock",
                    json={"quantity": 7},
                )
                assert restock.status_code == 200
                assert restock.json()["quantityOnHand"] == 15

                await client.post(f"/inventory/{item_id}/reserve", json={"quantity": 5})

                bad_adjust = await client.patch(
                    f"/inventory/{item_id}",
                    json={"quantityOnHand": 4},
                )
                assert bad_adjust.status_code == 400

    _run(body())
    _run(dispose_engines())


def test_reserve_release_and_commit(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/inventory", json=_inventory_payload(quantityOnHand=6))
                item_id = created.json()["id"]

                reserve = await client.post(f"/inventory/{item_id}/reserve", json={"quantity": 4})
                assert reserve.status_code == 200
                body = reserve.json()
                assert body["quantityReserved"] == 4
                assert body["available"] == 2

                over_reserve = await client.post(f"/inventory/{item_id}/reserve", json={"quantity": 3})
                assert over_reserve.status_code == 409

                release = await client.post(f"/inventory/{item_id}/release", json={"quantity": 2})
                assert release.status_code == 200
                assert release.json()["quantityReserved"] == 2

                commit = await client.post(f"/inventory/{item_id}/commit", json={"quantity": 2})
                assert commit.status_code == 200
                committed = commit.json()
                assert committed["quantityOnHand"] == 4
                assert committed["quantityReserved"] == 0

                events = await client.get(f"/inventory/{item_id}/events")
                event_types = [entry["type"] for entry in events.json()]
                assert "reserved" in event_types
                assert "released" in event_types
                assert "committed" in event_types

    _run(body())
    _run(dispose_engines())


def test_delete_and_missing(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/inventory", json=_inventory_payload())
                item_id = created.json()["id"]

                delete_resp = await client.delete(f"/inventory/{item_id}")
                assert delete_resp.status_code == 204

                missing = await client.get(f"/inventory/{item_id}")
                assert missing.status_code == 404

                missing_reserve = await client.post(f"/inventory/{item_id}/reserve", json={"quantity": 1})
                assert missing_reserve.status_code == 404

    _run(body())
    _run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
