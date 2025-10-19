import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.catalog_service.app.main import create_app
from services.catalog_service.app.models import Base
from services.common import ServiceSettings, create_engine, dispose_engines


def _sample_payload(sku: str = "SKU-001", price: Decimal = Decimal("19.99")) -> dict[str, Any]:
    return {
        "sku": sku,
        "name": "Sample Product",
        "description": "A product for testing",
        "price": str(price),
        "currency": "usd",
        "isActive": True,
        "categories": ["apparel", "featured"],
    }


def _run(coro):
    return asyncio.run(coro)


async def _prepare_app(tmp_path) -> FastAPI:
    db_file = tmp_path / "catalog.db"
    database_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = ServiceSettings(
        app_name="Catalog Service Test",
        enable_metrics=False,
        enable_tracing=False,
        database_url=database_url,
    )
    return create_app(settings)


def test_create_and_get_product(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/products", json=_sample_payload())
                assert response.status_code == 201
                payload = response.json()
                assert payload["sku"] == "SKU-001"
                assert payload["currency"] == "USD"
                assert payload["price"] == "19.99"

                duplicate = await client.post("/products", json=_sample_payload())
                assert duplicate.status_code == 409

                product_id = payload["id"]
                retrieved = await client.get(f"/products/{product_id}")
                assert retrieved.status_code == 200
                retrieved_payload = retrieved.json()
                assert retrieved_payload["categories"] == ["apparel", "featured"]

    _run(body())
    _run(dispose_engines())


def test_update_product_changes_categories_and_price(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_response = await client.post("/products", json=_sample_payload())
                product_id = create_response.json()["id"]

                patch_payload = {
                    "price": "24.50",
                    "categories": ["sale"],
                    "isActive": False,
                }
                update_response = await client.patch(f"/products/{product_id}", json=patch_payload)
                assert update_response.status_code == 200
                body = update_response.json()
                assert body["price"] == "24.50"
                assert body["categories"] == ["sale"]
                assert body["isActive"] is False

    _run(body())
    _run(dispose_engines())


def test_list_products_supports_filters(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/products", json=_sample_payload("SKU-100", Decimal("12.00")))
                await client.post(
                    "/products",
                    json={
                        **_sample_payload("SKU-200", Decimal("9.99")),
                        "categories": ["electronics"],
                    },
                )
                await client.post(
                    "/products",
                    json={
                        **_sample_payload("SKU-300", Decimal("29.00")),
                        "isActive": False,
                        "categories": ["electronics", "clearance"],
                    },
                )

                response = await client.get("/products", params={"category": "electronics"})
                assert response.status_code == 200
                data = response.json()
                assert data["total"] == 2
                assert len(data["items"]) == 2

                filtered = await client.get("/products", params={"onlyActive": "true"})
                filtered_data = filtered.json()
                assert filtered_data["total"] == 2
                assert all(item["isActive"] for item in filtered_data["items"])

    _run(body())
    _run(dispose_engines())


def test_delete_product_removes_entry(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_response = await client.post("/products", json=_sample_payload("SKU-DELETE"))
                product_id = create_response.json()["id"]

                delete_response = await client.delete(f"/products/{product_id}")
                assert delete_response.status_code == 204

                missing = await client.get(f"/products/{product_id}")
                assert missing.status_code == 404

    _run(body())
    _run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
