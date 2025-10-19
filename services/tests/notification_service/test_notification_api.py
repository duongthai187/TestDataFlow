import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.common import ServiceSettings, create_engine, dispose_engines
from services.common.kafka import KafkaConsumerStub
from services.notification_service.app.main import create_app
from services.notification_service.app.models import Base
from prometheus_client import REGISTRY


class _StubLimiter:
    def __init__(self, quota: int) -> None:
        self.quota = quota

    async def allow(self, _channel: str, *, amount: int = 1) -> bool:
        if amount <= self.quota:
            self.quota -= amount
            return True
        return False


def _run(coro):
    return asyncio.run(coro)


async def _prepare_app(tmp_path) -> FastAPI:
    db_file = tmp_path / "notifications.db"
    database_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = ServiceSettings(
        app_name="Notification Service Test",
        enable_metrics=False,
        enable_tracing=False,
        database_url=database_url,
    )
    return create_app(settings)


def _notification_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "recipient": "user@example.com",
        "channel": "email",
        "subject": "Welcome",
        "body": "Hello there",
        "template": "welcome",
        "metadata": {"lang": "en"},
    }
    payload.update(overrides)
    return payload


def _get_metric_value(name: str, labels: dict[str, str] | None = None) -> float:
    value = REGISTRY.get_sample_value(name, labels or {})
    return float(value) if value is not None else 0.0


class _MetricTracker:
    def __init__(self, name: str, labels: dict[str, str] | None = None) -> None:
        self.name = name
        self.labels = labels or {}
        self._baseline = _get_metric_value(name, self.labels)

    def delta(self) -> float:
        return _get_metric_value(self.name, self.labels) - self._baseline


def test_create_and_get_notification(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post("/notifications", json=_notification_payload())
                assert create_resp.status_code == 201
                created = create_resp.json()
                assert created["status"] == "pending"
                assert created["metadata"] == {"lang": "en"}
                notification_id = created["id"]

                get_resp = await client.get(f"/notifications/{notification_id}")
                assert get_resp.status_code == 200
                assert get_resp.json()["id"] == notification_id

    _run(body())
    _run(dispose_engines())


def test_list_and_filters(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/notifications", json=_notification_payload(recipient="other@example.com"))
                await client.post("/notifications", json=_notification_payload())

                list_resp = await client.get("/notifications", params={"recipient": "user@example.com"})
                assert list_resp.status_code == 200
                data = list_resp.json()
                assert data["total"] == 1
                assert data["items"][0]["recipient"] == "user@example.com"

    _run(body())
    _run(dispose_engines())


def test_send_notification_and_events(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/notifications", json=_notification_payload())
                notification_id = created.json()["id"]

                send_resp = await client.post(f"/notifications/{notification_id}/send")
                assert send_resp.status_code == 200
                sent_body = send_resp.json()
                assert sent_body["status"] == "sent"
                assert sent_body["sentAt"] is not None

                duplicate = await client.post(f"/notifications/{notification_id}/send")
                assert duplicate.status_code == 409

                events_resp = await client.get(f"/notifications/{notification_id}/events")
                events = events_resp.json()
                event_types = [event["type"] for event in events]
                assert "created" in event_types
                assert "sent" in event_types

    _run(body())
    _run(dispose_engines())


def test_fail_and_reschedule(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/notifications", json=_notification_payload())
                notification_id = created.json()["id"]

                fail_resp = await client.post(
                    f"/notifications/{notification_id}/fail",
                    json={"message": "bounce"},
                )
                assert fail_resp.status_code == 200
                assert fail_resp.json()["status"] == "failed"
                assert fail_resp.json()["errorMessage"] == "bounce"

                reschedule_resp = await client.post(
                    f"/notifications/{notification_id}/reschedule",
                    json={"sendAfter": "2025-01-01T00:00:00+00:00"},
                )
                assert reschedule_resp.status_code == 200
                returned = reschedule_resp.json()["sendAfter"]
                parsed = datetime.fromisoformat(returned.replace("Z", "+00:00"))
                assert parsed.isoformat() == "2025-01-01T00:00:00+00:00"

    _run(body())
    _run(dispose_engines())


def test_delete_and_missing(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/notifications", json=_notification_payload())
                notification_id = created.json()["id"]

                delete_resp = await client.delete(f"/notifications/{notification_id}")
                assert delete_resp.status_code == 204

                missing = await client.get(f"/notifications/{notification_id}")
                assert missing.status_code == 404

                missing_send = await client.post(f"/notifications/{notification_id}/send")
                assert missing_send.status_code == 404

    _run(body())
    _run(dispose_engines())


def test_preferences_crud(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            captured: list[dict[str, Any]] = []

            async def _capture(topic: str, payload: dict[str, Any]) -> None:
                captured.append({"topic": topic, "payload": payload})

            consumer = KafkaConsumerStub(["notification.preference.updated.v1"], _capture)
            await consumer.start()
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    empty_resp = await client.get("/notifications/preferences/42")
                    assert empty_resp.status_code == 200
                    assert empty_resp.json()["preferences"] == []

                    update_resp = await client.put(
                        "/notifications/preferences/42",
                        json={
                            "preferences": [
                                {"channel": "EMAIL", "optIn": True},
                                {"channel": "sms", "optIn": False},
                            ]
                        },
                    )
                    assert update_resp.status_code == 200
                    data = update_resp.json()
                    assert len(data["preferences"]) == 2
                    channels = {entry["channel"]: entry["optIn"] for entry in data["preferences"]}
                    assert channels == {"email": True, "sms": False}

                    second = await client.put(
                        "/notifications/preferences/42",
                        json={"preferences": [{"channel": "sms", "optIn": True}]},
                    )
                    assert second.status_code == 200
                    channels = {entry["channel"]: entry["optIn"] for entry in second.json()["preferences"]}
                    assert channels == {"email": True, "sms": True}
            finally:
                await consumer.stop()

            assert len(captured) >= 2
            first_event = captured[0]["payload"]
            assert first_event["customerId"] == 42
            first_channels = {entry["channel"]: entry["optIn"] for entry in first_event["preferences"]}
            assert first_channels == {"email": True, "sms": False}
            assert all(entry.get("updatedAt") for entry in first_event["preferences"])

            second_event = captured[-1]["payload"]
            assert second_event["customerId"] == 42
            second_channels = {entry["channel"]: entry["optIn"] for entry in second_event["preferences"]}
            assert second_channels == {"email": True, "sms": True}
            assert all(entry.get("updatedAt") for entry in second_event["preferences"])

    _run(body())
    _run(dispose_engines())


def test_template_crud(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post(
                    "/notifications/templates",
                    json={
                        "name": "order_shipped",
                        "channel": "EMAIL",
                        "locale": "EN_US",
                        "version": 1,
                        "subject": "Your order shipped",
                        "body": "Hello {{ name }}",
                        "metadata": {"category": "shipping"},
                    },
                )
                assert create_resp.status_code == 201
                created = create_resp.json()
                assert created["channel"] == "email"
                assert created["locale"] == "en-us"
                template_id = created["id"]

                list_resp = await client.get("/notifications/templates", params={"channel": "EMAIL"})
                assert list_resp.status_code == 200
                listed = list_resp.json()
                assert listed["total"] == 1
                assert listed["items"][0]["id"] == template_id

                get_resp = await client.get(f"/notifications/templates/{template_id}")
                assert get_resp.status_code == 200
                assert get_resp.json()["name"] == "order_shipped"

                update_resp = await client.put(
                    f"/notifications/templates/{template_id}",
                    json={
                        "subject": "Updated subject",
                        "metadata": None,
                        "version": 2,
                    },
                )
                assert update_resp.status_code == 200
                updated = update_resp.json()
                assert updated["subject"] == "Updated subject"
                assert updated["metadata"] is None
                assert updated["version"] == 2

                conflict_resp = await client.post(
                    "/notifications/templates",
                    json={
                        "name": "order_shipped",
                        "channel": "email",
                        "locale": "en-us",
                        "version": 2,
                        "body": "Conflict",
                    },
                )
                assert conflict_resp.status_code == 409

                delete_resp = await client.delete(f"/notifications/templates/{template_id}")
                assert delete_resp.status_code == 204

                missing_resp = await client.get(f"/notifications/templates/{template_id}")
                assert missing_resp.status_code == 404

    _run(body())
    _run(dispose_engines())


def test_order_status_event_triggers_notification(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            handler = app.state.notification_event_handler
            provider = app.state.notification_provider
            transport = ASGITransport(app=app)

            processed_metric = _MetricTracker(
                "notification_events_processed_total",
                {"topic": "order.status.changed.v1"},
            )
            sent_metric = _MetricTracker("notification_sent_total", {"channel": "email"})
            latency_count_metric = _MetricTracker(
                "notification_send_latency_seconds_count",
                {"channel": "email"},
            )
            dropped_metric = _MetricTracker(
                "notification_events_dropped_total",
                {"topic": "order.status.changed.v1", "reason": "opted_out"},
            )

            payload = {
                "previousStatus": "pending",
                "currentStatus": "shipped",
                "occurredAt": "2025-01-01T12:00:00Z",
                "order": {
                    "id": 321,
                    "customerId": 77,
                    "status": "processing",
                    "channel": "email",
                    "contact": {"email": "buyer@example.com"},
                },
            }

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await handler.handle("order.status.changed.v1", payload)
                list_resp = await client.get("/notifications", params={"channel": "email"})
                assert list_resp.status_code == 200
                body = list_resp.json()
                assert body["total"] == 1
                notification = body["items"][0]
                assert notification["recipient"] == "buyer@example.com"
                assert notification["subject"].startswith("Order 321 status updated")
            assert len(provider.sent) == 1
            sent = provider.sent[0]
            assert sent.channel == "email"
            assert "Order 321" in (sent.subject or "")
            assert "Previously it was Pending" in sent.body
            assert processed_metric.delta() == 1
            assert sent_metric.delta() == 1
            assert latency_count_metric.delta() == 1
            assert dropped_metric.delta() == 0

    _run(body())
    _run(dispose_engines())


def test_shipment_event_respects_preferences(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            handler = app.state.notification_event_handler
            provider = app.state.notification_provider
            transport = ASGITransport(app=app)

            processed_metric = _MetricTracker(
                "notification_events_processed_total",
                {"topic": "fulfillment.shipment.updated.v1"},
            )
            opt_out_metric = _MetricTracker("notification_opt_out_total", {"channel": "sms"})
            dropped_opt_out_metric = _MetricTracker(
                "notification_events_dropped_total",
                {"topic": "fulfillment.shipment.updated.v1", "reason": "opted_out"},
            )
            sent_metric = _MetricTracker("notification_sent_total", {"channel": "sms"})
            latency_count_metric = _MetricTracker(
                "notification_send_latency_seconds_count",
                {"channel": "sms"},
            )

            shipment_payload = {
                "customerId": 55,
                "orderId": 501,
                "status": "out_for_delivery",
                "trackingNumber": "1Z999",
                "channel": "sms",
                "contact": {"phone": "+15551234567"},
            }

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.put(
                    "/notifications/preferences/55",
                    json={"preferences": [{"channel": "sms", "optIn": False}]},
                )

            await handler.handle("fulfillment.shipment.updated.v1", shipment_payload)
            assert provider.sent == []

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.put(
                    "/notifications/preferences/55",
                    json={"preferences": [{"channel": "sms", "optIn": True}]},
                )

            await handler.handle("fulfillment.shipment.updated.v1", shipment_payload)

            assert len(provider.sent) == 1
            sent = provider.sent[0]
            assert sent.channel == "sms"
            assert sent.recipient == "+15551234567"
            assert sent.metadata is not None
            assert sent.metadata["topic"] == "fulfillment.shipment.updated.v1"
            assert sent.metadata["orderId"] == 501
            assert sent.metadata["trackingNumber"] == "1Z999"
            assert sent.metadata["status"] == "out_for_delivery"
        assert processed_metric.delta() == 1
        assert opt_out_metric.delta() == 1
        assert dropped_opt_out_metric.delta() == 1
        assert sent_metric.delta() == 1
        assert latency_count_metric.delta() == 1

    _run(body())
    _run(dispose_engines())


def test_batch_job_lifecycle(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                template_resp = await client.post(
                    "/notifications/templates",
                    json={
                        "name": "order_update",
                        "channel": "email",
                        "locale": "en-us",
                        "version": 1,
                        "subject": "Order {order_id} shipped",
                        "body": "Hello {name}",
                        "metadata": {"footer": "Thanks"},
                    },
                )
                template_id = template_resp.json()["id"]

                batch_resp = await client.post(
                    "/notifications/batch",
                    json={
                        "templateId": template_id,
                        "scheduledFor": "2025-02-01T12:00:00+00:00",
                        "recipients": [
                            {"recipient": "a@example.com", "metadata": {"name": "Alice", "order_id": "1"}},
                            {"recipient": "b@example.com", "metadata": {"name": "Bob", "order_id": "2"}},
                        ],
                    },
                )
                assert batch_resp.status_code == 202
                job_payload = batch_resp.json()
                job_id = job_payload["id"]
                assert job_payload["processedCount"] == 2
                assert job_payload["status"] == "completed"

                list_resp = await client.get("/notifications/jobs")
                assert list_resp.status_code == 200
                assert list_resp.json()["total"] == 1

                detail_resp = await client.get(f"/notifications/jobs/{job_id}")
                assert detail_resp.status_code == 200
                detail = detail_resp.json()
                assert len(detail["notifications"]) == 2
                created_subjects = {item["subject"] for item in detail["notifications"]}
                assert "Order 1 shipped" in created_subjects
                assert "Order 2 shipped" in created_subjects

                notifications_resp = await client.get("/notifications", params={"channel": "email"})
                assert notifications_resp.json()["total"] == 2

    _run(body())
    _run(dispose_engines())


def test_send_rate_limited(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post("/notifications", json=_notification_payload())
                notification_id = create_resp.json()["id"]

                app.state.rate_limiter = _StubLimiter(quota=0)

                send_resp = await client.post(f"/notifications/{notification_id}/send")
                assert send_resp.status_code == 429

    _run(body())
    _run(dispose_engines())


def test_batch_rate_limited(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                template_resp = await client.post(
                    "/notifications/templates",
                    json={
                        "name": "bulk",
                        "channel": "email",
                        "locale": "en-us",
                        "version": 1,
                        "body": "Hello",
                    },
                )
                template_id = template_resp.json()["id"]

                app.state.rate_limiter = _StubLimiter(quota=1)

                batch_resp = await client.post(
                    "/notifications/batch",
                    json={
                        "templateId": template_id,
                        "recipients": [
                            {"recipient": "a@example.com"},
                            {"recipient": "b@example.com"},
                        ],
                    },
                )
                assert batch_resp.status_code == 429

                jobs_resp = await client.get("/notifications/jobs")
                assert jobs_resp.json()["total"] == 0

    _run(body())
    _run(dispose_engines())


def test_support_event_triggers_notification(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                pref_resp = await client.put(
                    "/notifications/preferences/101",
                    json={"preferences": [{"channel": "email", "optIn": True}]},
                )
                assert pref_resp.status_code == 200

                await app.state.kafka_producer.send(
                    "support.case.updated.v1",
                    {
                        "ticket": {
                            "id": "case-1001",
                            "subject": "Package delay",
                            "customerId": 101,
                            "channel": "email",
                            "status": "pending",
                        },
                        "changeType": "status.changed",
                        "currentStatus": "pending",
                        "occurredAt": "2025-01-02T12:00:00Z",
                    },
                )

                await asyncio.sleep(0)

                sent = list(app.state.notification_provider.sent)
                assert len(sent) == 1
                assert sent[0].recipient == "customer-101@example.com"
                assert "support case" in (sent[0].subject or "").lower()

                list_resp = await client.get(
                    "/notifications",
                    params={"recipient": "customer-101@example.com"},
                )
                assert list_resp.status_code == 200
                data = list_resp.json()
                assert data["total"] == 1
                assert data["items"][0]["status"] == "sent"

    _run(body())
    _run(dispose_engines())


def test_support_event_respects_preferences(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                pref_resp = await client.put(
                    "/notifications/preferences/202",
                    json={"preferences": [{"channel": "email", "optIn": False}]},
                )
                assert pref_resp.status_code == 200

                await app.state.kafka_producer.send(
                    "support.case.updated.v1",
                    {
                        "ticket": {
                            "id": "case-2002",
                            "subject": "Payment issue",
                            "customerId": 202,
                            "channel": "email",
                            "status": "open",
                        },
                        "changeType": "conversation.added",
                        "conversation": {
                            "id": "conv-1",
                            "authorType": "agent",
                            "message": "We are reviewing your request.",
                        },
                        "occurredAt": "2025-01-03T09:00:00Z",
                    },
                )

                await asyncio.sleep(0)

                assert not app.state.notification_provider.sent

                list_resp = await client.get(
                    "/notifications",
                    params={"recipient": "customer-202@example.com"},
                )
                assert list_resp.status_code == 200
                assert list_resp.json()["total"] == 0

    _run(body())
    _run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
