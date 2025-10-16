import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.common import ServiceSettings, create_engine, dispose_engines
from services.customer_service.app.main import create_app
from services.customer_service.app.models import Base


def _sample_payload(email: str = "alice@example.com") -> dict[str, Any]:
	return {
		"email": email,
		"fullName": "Alice Example",
		"phoneNumber": "+12025550100",
		"preferredLanguage": "en",
		"addresses": [
			{
				"label": "home",
				"line1": "123 Main St",
				"line2": "Apt 4",
				"city": "Seattle",
				"state": "WA",
				"postalCode": "98101",
				"country": "US",
			}
		],
	}


def _run(coro):
	return asyncio.run(coro)


async def _prepare_app(tmp_path) -> FastAPI:
	db_file = tmp_path / "customer.db"
	database_url = f"sqlite+aiosqlite:///{db_file}"

	engine = create_engine(database_url)
	async with engine.begin() as conn:
		await conn.run_sync(Base.metadata.create_all)

	settings = ServiceSettings(
		app_name="Customer Service Test",
		enable_metrics=False,
		enable_tracing=False,
		database_url=database_url,
	)
	return create_app(settings)


def test_create_customer_returns_payload(tmp_path) -> None:
	app = _run(_prepare_app(tmp_path))

	async def body() -> None:
		async with lifespan(app):
			transport = ASGITransport(app=app)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				response = await client.post("/customers", json=_sample_payload())

				assert response.status_code == 201
				payload = response.json()
				assert payload["fullName"] == "Alice Example"
				assert payload["segments"] == []
				assert payload["addresses"][0]["postalCode"] == "98101"

				duplicate = await client.post("/customers", json=_sample_payload())
				assert duplicate.status_code == 409

	_run(body())
	_run(dispose_engines())


def test_update_customer_replaces_addresses(tmp_path) -> None:
	app = _run(_prepare_app(tmp_path))

	async def body() -> None:
		async with lifespan(app):
			transport = ASGITransport(app=app)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				create_response = await client.post("/customers", json=_sample_payload())
				customer_id = create_response.json()["id"]

				patch_payload = {
					"fullName": "Alice Updated",
					"addresses": [
						{
							"label": "office",
							"line1": "500 Madison Ave",
							"city": "New York",
							"state": "NY",
							"postalCode": "10022",
							"country": "US",
						}
					],
				}
				update_response = await client.patch(f"/customers/{customer_id}", json=patch_payload)
				assert update_response.status_code == 200
				body = update_response.json()
				assert body["fullName"] == "Alice Updated"
				assert len(body["addresses"]) == 1
				assert body["addresses"][0]["label"] == "office"

	_run(body())
	_run(dispose_engines())


def test_segment_assignment_and_cleanup(tmp_path) -> None:
	app = _run(_prepare_app(tmp_path))

	async def body() -> None:
		async with lifespan(app):
			transport = ASGITransport(app=app)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				create_response = await client.post("/customers", json=_sample_payload())
				customer_id = create_response.json()["id"]

				assign_response = await client.post(
					f"/customers/{customer_id}/segments", json={"segment": "vip"}
				)
				assert assign_response.status_code == 201
				assignment = assign_response.json()
				assert assignment["segment"] == "vip"
				assert assignment["customerId"] == customer_id

				get_response = await client.get(f"/customers/{customer_id}")
				assert get_response.json()["segments"] == ["vip"]

				clear_response = await client.delete(f"/customers/{customer_id}/segments")
				assert clear_response.status_code == 204

				refreshed = await client.get(f"/customers/{customer_id}")
				assert refreshed.json()["segments"] == []

				delete_response = await client.delete(f"/customers/{customer_id}")
				assert delete_response.status_code == 204

				missing = await client.get(f"/customers/{customer_id}")
				assert missing.status_code == 404

	_run(body())
	_run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
	async with app.router.lifespan_context(app):
		yield
