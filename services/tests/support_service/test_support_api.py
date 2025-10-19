import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from services.common import ServiceSettings, create_engine, dispose_engines
from services.common.kafka import KafkaProducerStub
from services.support_service.app.main import create_app
from services.support_service.app.models import Base


def _run(coro):
    return asyncio.run(coro)


class StubEventPublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def case_opened(self, ticket, initial_message):
        self.events.append(
            {
                "type": "support.case.opened.v1",
                "ticketId": ticket.id,
                "initialMessageId": getattr(initial_message, "id", None),
            }
        )

    async def conversation_added(self, ticket, conversation):
        self.events.append(
            {
                "type": "support.case.updated.v1",
                "changeType": "conversation.added",
                "ticketId": ticket.id,
                "conversationId": conversation.id,
            }
        )

    async def status_changed(self, ticket, previous_status: str):
        self.events.append(
            {
                "type": "support.case.updated.v1",
                "changeType": "status.changed",
                "ticketId": ticket.id,
                "previousStatus": previous_status,
                "currentStatus": ticket.status,
            }
        )
        if ticket.status.lower() == "closed":
            self.events.append(
                {
                    "type": "support.case.closed.v1",
                    "ticketId": ticket.id,
                    "previousStatus": previous_status,
                }
            )

    async def attachment_added(self, ticket, attachment):
        self.events.append(
            {
                "type": "support.case.updated.v1",
                "changeType": "attachment.added",
                "ticketId": ticket.id,
                "attachmentId": attachment.id,
            }
        )

async def _prepare_app(tmp_path) -> FastAPI:
    db_file = tmp_path / "support.db"
    database_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = ServiceSettings(
        app_name="Support Service Test",
        enable_metrics=False,
        enable_tracing=False,
        database_url=database_url,
        support_attachment_dir=str(tmp_path / "attachments"),
        support_attachment_base_url="http://storage.local/attachments",
    )
    return create_app(settings)


def _ticket_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "subject": "Delayed shipment",
        "description": "Customer reports late delivery",
        "customerId": "cust-123",
        "channel": "email",
        "priority": "high",
        "assignedAgentId": "agent-1",
        "context": [
            {
                "type": "order",
                "orderId": "order-456",
                "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
            }
        ],
        "initialMessage": {
            "authorType": "customer",
            "message": "Where is my package?",
        },
    }
    payload.update(overrides)
    return payload


class _MetricTracker:
    def __init__(self, name: str, labels: dict[str, str] | None = None) -> None:
        self.name = name
        self.labels = labels or {}
        baseline = REGISTRY.get_sample_value(name, self.labels)
        self._baseline = baseline if baseline is not None else 0.0

    def delta(self) -> float:
        current = REGISTRY.get_sample_value(self.name, self.labels)
        value = current if current is not None else 0.0
        return value - self._baseline


def test_create_ticket_with_initial_message(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            event_stub = StubEventPublisher()
            app.state.event_publisher = event_stub
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post("/support/cases", json=_ticket_payload())
                assert create_resp.status_code == 201
                data = create_resp.json()
                assert data["status"] == "open"
                assert data["priority"] == "high"
                assert data["messages"][0]["authorType"] == "customer"
                assert any(entry["type"] == "conversation" for entry in data["timeline"])
                assert data["attachments"] == []

                ticket_id = data["id"]
                get_resp = await client.get(f"/support/cases/{ticket_id}")
                assert get_resp.status_code == 200
                basic = get_resp.json()
                assert basic["id"] == ticket_id
                assert basic["timeline"] == []
                assert basic["attachments"] == []

                opened_events = [evt for evt in event_stub.events if evt["type"] == "support.case.opened.v1"]
                assert len(opened_events) == 1
                assert opened_events[0]["ticketId"] == ticket_id
                assert opened_events[0]["initialMessageId"] is not None

    _run(body())
    _run(dispose_engines())


def test_get_ticket_with_timeline(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            event_stub = StubEventPublisher()
            app.state.event_publisher = event_stub
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                ticket_id = (
                    await client.post("/support/cases", json=_ticket_payload(assignedAgentId=None))
                ).json()["id"]

                message_resp = await client.post(
                    f"/support/cases/{ticket_id}/messages",
                    json={
                        "authorType": "agent",
                        "message": "We are checking with the carrier.",
                        "attachmentUri": "https://files.example.com/transcript.txt",
                    },
                )
                assert message_resp.status_code == 200

                detail_resp = await client.get(
                    f"/support/cases/{ticket_id}",
                    params={"includeTimeline": "true"},
                )
                assert detail_resp.status_code == 200
                detail = detail_resp.json()
                assert len(detail["messages"]) == 2
                assert len(detail["timeline"]) >= 2
                assert any(entry.get("authorType") == "agent" for entry in detail["timeline"])
                assert detail["attachments"] == []
                assert any(
                    entry.get("attachmentUri") == "https://files.example.com/transcript.txt"
                    for entry in detail["timeline"]
                    if entry.get("type") == "conversation"
                )

                conversation_events = [evt for evt in event_stub.events if evt.get("changeType") == "conversation.added"]
                assert conversation_events
                assert conversation_events[-1]["ticketId"] == ticket_id

    _run(body())
    _run(dispose_engines())


def test_upload_attachment_and_list(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            event_stub = StubEventPublisher()
            app.state.event_publisher = event_stub
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                ticket_id = (
                    await client.post("/support/cases", json=_ticket_payload())
                ).json()["id"]

                stored_tracker = _MetricTracker(
                    "support_attachment_stored_total", {"content_type": "text/plain"}
                )
                bytes_tracker = _MetricTracker("support_attachment_backlog_bytes")
                files_tracker = _MetricTracker("support_attachment_backlog_files")

                file_bytes = b"Support transcript"
                upload_resp = await client.post(
                    f"/support/cases/{ticket_id}/attachments",
                    files={"file": ("transcript.txt", file_bytes, "text/plain")},
                )
                assert upload_resp.status_code == 201
                attachment = upload_resp.json()
                assert attachment["ticketId"] == ticket_id
                assert attachment["filename"] == "transcript.txt"
                assert attachment["contentType"] == "text/plain"
                assert attachment["sizeBytes"] == len(file_bytes)
                assert attachment["uri"].endswith("transcript.txt")

                list_resp = await client.get(f"/support/cases/{ticket_id}/attachments")
                assert list_resp.status_code == 200
                attachments = list_resp.json()
                assert len(attachments) == 1
                assert attachments[0]["id"] == attachment["id"]

                detail_resp = await client.get(f"/support/cases/{ticket_id}")
                assert detail_resp.status_code == 200
                detail = detail_resp.json()
                assert len(detail["attachments"]) == 1
                assert detail["attachments"][0]["uri"] == attachment["uri"]

                timeline_resp = await client.get(
                    f"/support/cases/{ticket_id}", params={"includeTimeline": "true"}
                )
                assert timeline_resp.status_code == 200
                timeline_detail = timeline_resp.json()
                assert any(entry["type"] == "attachment" for entry in timeline_detail["timeline"])

                assert stored_tracker.delta() == 1
                assert files_tracker.delta() == 1
                assert bytes_tracker.delta() == len(file_bytes)

                relative_path = attachment["uri"].replace(
                    "http://storage.local/attachments/", "", 1
                )
                stored_path = Path(tmp_path / "attachments" / relative_path)
                assert stored_path.exists()
                assert stored_path.read_bytes() == file_bytes

                attachment_events = [evt for evt in event_stub.events if evt.get("changeType") == "attachment.added"]
                assert attachment_events
                assert attachment_events[-1]["attachmentId"] == attachment["id"]

    _run(body())
    _run(dispose_engines())


def test_update_status_and_workload(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            event_stub = StubEventPublisher()
            app.state.event_publisher = event_stub
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                ticket_id = (
                    await client.post("/support/cases", json=_ticket_payload(assignedAgentId="agent-2"))
                ).json()["id"]

                workload_resp = await client.get("/support/agents/agent-2/workload")
                assert workload_resp.status_code == 200
                workload = workload_resp.json()
                assert workload["open"] == 1

                update_resp = await client.post(
                    f"/support/cases/{ticket_id}/status",
                    params={"status": "resolved", "assignedAgentId": "agent-2"},
                )
                assert update_resp.status_code == 200
                assert update_resp.json()["status"] == "resolved"

                workload_after = await client.get("/support/agents/agent-2/workload")
                assert workload_after.status_code == 200
                assert workload_after.json()["resolved"] == 1

                status_events = [evt for evt in event_stub.events if evt.get("changeType") == "status.changed"]
                assert status_events
                assert status_events[-1]["ticketId"] == ticket_id
                assert status_events[-1]["currentStatus"] == "resolved"

    _run(body())
    _run(dispose_engines())


def test_close_ticket_with_resolution_message(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            event_stub = StubEventPublisher()
            app.state.event_publisher = event_stub
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                ticket_payload = _ticket_payload()
                create_resp = await client.post("/support/cases", json=ticket_payload)
                assert create_resp.status_code == 201
                ticket_id = create_resp.json()["id"]

                close_payload = {
                    "message": "Package delivered successfully",
                    "authorType": "agent",
                    "sentiment": "positive",
                    "metadata": {"resolution": "Confirmed with carrier"},
                    "assignedAgentId": "agent-77",
                }
                close_resp = await client.post(
                    f"/support/cases/{ticket_id}/close",
                    json=close_payload,
                )
                assert close_resp.status_code == 200
                detail = close_resp.json()
                assert detail["status"] == "closed"
                assert detail["assignedAgentId"] == "agent-77"
                assert detail["messages"][-1]["message"] == "Package delivered successfully"
                assert detail["messages"][-1]["authorType"] == "agent"
                assert any(
                    entry.get("type") == "conversation" and entry.get("message") == "Package delivered successfully"
                    for entry in detail["timeline"]
                )

                conversation_events = [evt for evt in event_stub.events if evt.get("changeType") == "conversation.added"]
                assert conversation_events
                assert conversation_events[-1]["ticketId"] == ticket_id

                status_events = [evt for evt in event_stub.events if evt.get("changeType") == "status.changed"]
                assert status_events
                assert status_events[-1]["ticketId"] == ticket_id
                assert status_events[-1]["currentStatus"] == "closed"

                closed_events = [evt for evt in event_stub.events if evt.get("type") == "support.case.closed.v1"]
                assert closed_events
                assert closed_events[-1]["ticketId"] == ticket_id

    _run(body())
    _run(dispose_engines())


def test_close_ticket_without_message(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            event_stub = StubEventPublisher()
            app.state.event_publisher = event_stub
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                ticket_payload = _ticket_payload()
                create_resp = await client.post("/support/cases", json=ticket_payload)
                assert create_resp.status_code == 201
                ticket_id = create_resp.json()["id"]

                close_resp = await client.post(f"/support/cases/{ticket_id}/close")
                assert close_resp.status_code == 200
                detail = close_resp.json()
                assert detail["status"] == "closed"
                assert detail["assignedAgentId"] == ticket_payload["assignedAgentId"]
                assert len(detail["messages"]) == 1
                assert detail["messages"][0]["message"] == ticket_payload["initialMessage"]["message"]

                conversation_events = [evt for evt in event_stub.events if evt.get("changeType") == "conversation.added"]
                assert not conversation_events

                status_events = [evt for evt in event_stub.events if evt.get("changeType") == "status.changed"]
                assert status_events
                assert status_events[-1]["ticketId"] == ticket_id
                assert status_events[-1]["currentStatus"] == "closed"

                closed_events = [evt for evt in event_stub.events if evt.get("type") == "support.case.closed.v1"]
                assert closed_events
                assert closed_events[-1]["ticketId"] == ticket_id

    _run(body())
    _run(dispose_engines())


def test_fulfillment_event_appends_conversation(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            event_stub = StubEventPublisher()
            app.state.event_publisher = event_stub
            if getattr(app.state, "fulfillment_handler", None) is not None:
                app.state.fulfillment_handler.event_publisher = event_stub
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                ticket_payload = _ticket_payload()
                ticket_payload["context"].append(
                    {
                        "type": "shipment",
                        "shipmentId": 301,
                        "trackingNumber": "ZX123",
                    }
                )
                create_resp = await client.post("/support/cases", json=ticket_payload)
                assert create_resp.status_code == 201
                ticket_id = create_resp.json()["id"]

                producer = KafkaProducerStub()
                await producer.connect()
                await producer.send(
                    "fulfillment.shipment.updated.v1",
                    {
                        "eventType": "fulfillment.shipment.updated.v1",
                        "orderId": ticket_payload["context"][0]["orderId"],
                        "shipmentId": 301,
                        "trackingNumber": "ZX123",
                        "status": "in_transit",
                        "carrier": "VNPOST",
                        "occurredAt": "2025-01-03T08:00:00Z",
                    },
                )
                await producer.close()

                detail_resp = await client.get(f"/support/cases/{ticket_id}")
                assert detail_resp.status_code == 200
                detail = detail_resp.json()
                assert len(detail["messages"]) == 2
                assert detail["messages"][-1]["authorType"] == "bot"
                assert detail["messages"][-1]["message"].startswith("Shipment ZX123 updated to In transit")

                timeline_resp = await client.get(
                    f"/support/cases/{ticket_id}", params={"includeTimeline": "true"}
                )
                assert timeline_resp.status_code == 200
                timeline = timeline_resp.json()
                assert any(
                    entry.get("type") == "conversation" and entry.get("message", "").startswith("Shipment ZX123 updated")
                    for entry in timeline["timeline"]
                )

                conversation_events = [evt for evt in event_stub.events if evt.get("changeType") == "conversation.added"]
                assert conversation_events
                assert conversation_events[-1]["ticketId"] == ticket_id

    _run(body())
    _run(dispose_engines())


def test_ticket_not_found(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    async def body() -> None:
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                missing = await client.get("/support/cases/unknown")
                assert missing.status_code == 404

                missing_message = await client.post(
                    "/support/cases/unknown/messages",
                    json={"authorType": "agent", "message": "Hello"},
                )
                assert missing_message.status_code == 404

    _run(body())
    _run(dispose_engines())


def test_timeline_endpoint_uses_aggregator(tmp_path) -> None:
    app = _run(_prepare_app(tmp_path))

    class StubAggregator:
        def __init__(self) -> None:
            self.invalidated: list[str] = []
            self.collected: list[str] = []

        async def collect(self, ticket) -> list[dict[str, object]]:  # pragma: no cover - simple stub
            self.collected.append(ticket.id)
            return [
                {
                    "source": "stub",
                    "type": "external",
                    "timestamp": datetime(2025, 1, 2, tzinfo=timezone.utc).isoformat(),
                    "note": "Carrier picked up package",
                }
            ]

        async def invalidate(self, ticket_id: str) -> None:
            self.invalidated.append(ticket_id)

    async def body() -> None:
        async with lifespan(app):
            stub = StubAggregator()
            event_stub = StubEventPublisher()
            app.state.timeline_aggregator = stub
            app.state.event_publisher = event_stub
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create_resp = await client.post(
                    "/support/cases",
                    json=_ticket_payload(
                        context=[
                            {
                                "type": "order",
                                "orderId": 101,
                                "timestamp": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
                            }
                        ]
                    ),
                )
                assert create_resp.status_code == 201
                ticket_id = create_resp.json()["id"]
                assert ticket_id in stub.invalidated

                detail_resp = await client.get(
                    f"/support/cases/{ticket_id}",
                    params={"includeTimeline": "true"},
                )
                assert detail_resp.status_code == 200
                detail = detail_resp.json()
                assert ticket_id in stub.collected
                assert any(entry.get("source") == "stub" for entry in detail["timeline"])
                assert detail["attachments"] == []

                refresh_resp = await client.post(f"/support/cases/{ticket_id}/timeline/refresh")
                assert refresh_resp.status_code == 200
                refreshed = refresh_resp.json()
                assert ticket_id in stub.invalidated  # invalidate called again for refresh
                assert ticket_id in stub.collected
                assert len(refreshed["timeline"]) >= len(detail["timeline"])
                assert any(entry.get("source") == "stub" for entry in refreshed["timeline"])

                opened_events = [evt for evt in event_stub.events if evt["type"] == "support.case.opened.v1"]
                assert opened_events
                assert opened_events[0]["ticketId"] == ticket_id

    _run(body())
    _run(dispose_engines())


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with app.router.lifespan_context(app):
        yield
