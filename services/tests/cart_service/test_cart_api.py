import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.cart_service.app.main import create_app
from services.cart_service.app.models import Base
from services.common import ServiceSettings, create_engine, dispose_engines


def _sample_item(sku: str = "SKU-1", quantity: int = 1, price: Decimal = Decimal("5.00")) -> dict[str, Any]:
    return {
        "sku": sku,
        "name": f"Product {sku}",
        "quantity": quantity,
        "unitPrice": str(price),
    }


def _run(coro):
    return asyncio.run(coro)


async def _prepare_app(tmp_path) -> FastAPI:
    db_file = tmp_path / "cart.db"
    database_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = ServiceSettings(
        app_name="Cart Service Test",
        enable_metrics=False,
        enable_tracing=False,
        database_url=database_url,
    )
    return create_app(settings)


def test_add_and_get_cart(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                add_response = await client.post("/carts/1/items", json=_sample_item())
                assert add_response.status_code == 201
                payload = add_response.json()
                assert payload["customerId"] == 1
                assert payload["total"] == "5.00"

                get_response = await client.get("/carts/1")
                assert get_response.status_code == 200
                body = get_response.json()
                assert len(body["items"]) == 1
                assert body["items"][0]["sku"] == "SKU-1"

    _run(body())
    _run(dispose_engines())


def test_update_and_remove_item(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/carts/2/items", json=_sample_item("SKU-2", 2))

                update_response = await client.patch(
                    "/carts/2/items/SKU-2",
                    json={"quantity": 3, "unitPrice": "6.50"},
                )
                assert update_response.status_code == 200
                updated = update_response.json()
                assert updated["total"] == "19.50"

                remove_response = await client.delete("/carts/2/items/SKU-2")
                assert remove_response.status_code == 200
                emptied = remove_response.json()
                assert emptied["items"] == []

    _run(body())
    _run(dispose_engines())


def test_clear_and_totals(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/carts/3/items", json=_sample_item("SKU-3", 2))
                await client.post("/carts/3/items", json=_sample_item("SKU-4", 1, Decimal("3.25")))

                totals = await client.get("/carts/3/totals")
                assert totals.status_code == 200
                totals_body = totals.json()
                assert totals_body["totalItems"] == 3
                assert totals_body["totalAmount"] == "13.25"

                clear_response = await client.delete("/carts/3")
                assert clear_response.status_code == 204

                totals_empty = await client.get("/carts/3/totals")
                assert totals_empty.json()["totalItems"] == 0

    _run(body())
    _run(dispose_engines())


def test_merge_carts(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/carts/10/items", json=_sample_item("SKU-10", 1, Decimal("2.10")))
                await client.post("/carts/10/items", json=_sample_item("SKU-11", 2, Decimal("4.00")))
                await client.post("/carts/20/items", json=_sample_item("SKU-12", 1, Decimal("6.00")))

                merge_response = await client.post(
                    "/carts/merge",
                    json={"fromCustomerId": 10, "toCustomerId": 20},
                )
                assert merge_response.status_code == 200
                body = merge_response.json()
                assert body["customerId"] == 20
                assert len(body["items"]) == 3
                assert body["total"] == "16.10"

    _run(body())
    _run(dispose_engines())


def test_merge_from_nonexistent_cart(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/carts/30/items", json=_sample_item())
                merge_response = await client.post(
                    "/carts/merge",
                    json={"fromCustomerId": 999, "toCustomerId": 30},
                )
                assert merge_response.status_code == 200
                assert merge_response.json()["total"] == "5.00"

    _run(body())
    _run(dispose_engines())


def test_update_missing_item_returns_404(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                missing = await client.patch("/carts/50/items/SKU-UNKNOWN", json={"quantity": 1})
                assert missing.status_code == 404

    _run(body())
    _run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
