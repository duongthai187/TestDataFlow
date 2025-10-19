import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.common import ServiceSettings, create_engine, dispose_engines
from services.pricing_service.app.main import create_app
from services.pricing_service.app.models import Base


def _sample_payload(sku: str = "SKU-001", price: Decimal = Decimal("10.00")) -> dict[str, Any]:
    return {
        "sku": sku,
        "region": "us",
        "currency": "usd",
        "price": str(price),
        "priority": 10,
        "startAt": datetime.now(timezone.utc).isoformat(),
        "endAt": None,
        "isActive": True,
    }


def _run(coro):
    return asyncio.run(coro)


async def _prepare_app(tmp_path) -> FastAPI:
    db_file = tmp_path / "pricing.db"
    database_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = ServiceSettings(
        app_name="Pricing Service Test",
        enable_metrics=False,
        enable_tracing=False,
        database_url=database_url,
    )
    return create_app(settings)


def test_create_and_resolve_price_rule(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/prices", json=_sample_payload())
                assert response.status_code == 201
                payload = response.json()
                assert payload["price"] == "10.00"
                rule_id = payload["id"]

                resolved = await client.get(
                    "/prices/resolve",
                    params={"sku": "SKU-001", "region": "us"},
                )
                assert resolved.status_code == 200
                resolved_payload = resolved.json()
                assert resolved_payload["price"] == "10.00"
                assert resolved_payload["rule"]["id"] == rule_id

    _run(body())
    _run(dispose_engines())


def test_update_price_rule_changes_value(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_response = await client.post("/prices", json=_sample_payload("SKU-200"))
                rule_id = create_response.json()["id"]

                patch_payload = {"price": "14.75", "isActive": False}
                update_response = await client.patch(f"/prices/{rule_id}", json=patch_payload)
                assert update_response.status_code == 200
                updated = update_response.json()
                assert updated["price"] == "14.75"
                assert updated["isActive"] is False

    _run(body())
    _run(dispose_engines())


def test_list_filters_by_region_and_activity(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/prices", json=_sample_payload("SKU-300", Decimal("5.00")))
                await client.post(
                    "/prices",
                    json={
                        **_sample_payload("SKU-400", Decimal("12.00")),
                        "region": "eu",
                    },
                )
                await client.post(
                    "/prices",
                    json={
                        **_sample_payload("SKU-300", Decimal("7.50")),
                        "region": None,
                        "priority": 50,
                    },
                )

                response = await client.get(
                    "/prices",
                    params={"sku": "SKU-300", "region": "us", "activeOnly": "true"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["total"] == 2
                assert len(data["items"]) == 2

    _run(body())
    _run(dispose_engines())


def test_resolution_fallback_to_global_rule(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    "/prices",
                    json={
                        **_sample_payload("SKU-900", Decimal("3.50")),
                        "region": None,
                    },
                )
                await client.post(
                    "/prices",
                    json={
                        **_sample_payload("SKU-900", Decimal("4.25")),
                        "region": "us",
                        "startAt": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                    },
                )

                response = await client.get(
                    "/prices/resolve",
                    params={"sku": "SKU-900", "region": "us"},
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["price"] == "3.50"

                future = await client.get(
                    "/prices/resolve",
                    params={
                        "sku": "SKU-900",
                        "region": "us",
                        "effectiveAt": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
                    },
                )
                assert future.status_code == 200
                future_payload = future.json()
                assert future_payload["price"] == "4.25"

    _run(body())
    _run(dispose_engines())


def test_delete_price_rule(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_response = await client.post("/prices", json=_sample_payload("SKU-DEL"))
                rule_id = create_response.json()["id"]

                delete_response = await client.delete(f"/prices/{rule_id}")
                assert delete_response.status_code == 204

                missing = await client.get(f"/prices/{rule_id}")
                assert missing.status_code == 404

    _run(body())
    _run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
