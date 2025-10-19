import json
from collections import Counter
from typing import cast

import pytest
from httpx import AsyncClient, MockTransport, Request, Response
from prometheus_client import REGISTRY

from services.common.cache import RedisType
from services.support_service.app.models import SupportTicket
from services.support_service.app.timeline import TimelineAggregator


class _MemoryRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002 - TTL ignored in stub
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def close(self) -> None:
        self._store.clear()


class _ErrorRedis:
    def __init__(self) -> None:
        self.get_calls = 0
        self.set_calls = 0
        self.delete_calls = 0

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        raise RuntimeError(f"cache get failure for {key}")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self.set_calls += 1
        raise RuntimeError(f"cache set failure for {key}")

    async def delete(self, key: str) -> None:
        self.delete_calls += 1
        raise RuntimeError(f"cache delete failure for {key}")


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


@pytest.mark.asyncio
async def test_timeline_aggregator_collects_and_caches() -> None:
    call_counter: Counter[str] = Counter()

    def handler(request: Request) -> Response:
        call_counter[str(request.url.path)] += 1
        path = request.url.path
        if path.endswith("/orders/101"):
            payload = {
                "id": 101,
                "status": "fulfilled",
                "grandTotal": "149.99",
                "createdAt": "2025-01-01T10:00:00+00:00",
                "updatedAt": "2025-01-02T10:00:00+00:00",
            }
            return Response(200, json=payload)
        if path.endswith("/orders/101/events"):
            events = [
                {
                    "type": "order.status.changed",
                    "payload": {"status": "SHIPPED"},
                    "createdAt": "2025-01-02T12:00:00+00:00",
                }
            ]
            return Response(200, json=events)
        if path.endswith("/payments/501"):
            payment = {
                "id": 501,
                "orderId": 101,
                "status": "captured",
                "amount": "149.99",
                "updatedAt": "2025-01-02T11:00:00+00:00",
            }
            return Response(200, json=payment)
        if path.endswith("/fulfillment/shipments/301"):
            shipment = {
                "id": 301,
                "orderId": 101,
                "status": "in_transit",
                "trackingNumber": "ZX123",
                "updatedAt": "2025-01-03T08:00:00+00:00",
            }
            return Response(200, json=shipment)
        return Response(404)

    transport = MockTransport(handler)
    client = AsyncClient(transport=transport)
    redis = cast(RedisType, _MemoryRedis())

    aggregator = TimelineAggregator(
        client=client,
        redis=redis,
        cache_ttl=60,
        order_base_url="http://order.local",
        payment_base_url="http://payment.local",
        fulfillment_base_url="http://fulfillment.local",
    )

    miss_tracker = _MetricTracker("support_timeline_cache_events_total", {"event": "miss"})
    hit_tracker = _MetricTracker("support_timeline_cache_events_total", {"event": "hit"})
    write_tracker = _MetricTracker("support_timeline_cache_events_total", {"event": "write"})
    invalidate_tracker = _MetricTracker(
        "support_timeline_cache_events_total", {"event": "invalidate"}
    )
    remote_count_tracker = _MetricTracker(
        "support_timeline_collect_seconds_count", {"source": "remote"}
    )
    cache_count_tracker = _MetricTracker(
        "support_timeline_collect_seconds_count", {"source": "cache"}
    )
    failure_tracker = _MetricTracker(
        "support_timeline_collection_failures_total",
        {"stage": "aggregate"},
    )

    ticket = SupportTicket(
        id="ticket-1",
        subject="Delayed shipment",
        description=None,
        customer_id="cust-1",
        status="open",
        priority="normal",
        channel="email",
        assigned_agent_id=None,
        context_json=json.dumps(
            [
                {"type": "order", "orderId": 101},
                {"type": "payment", "paymentId": 501},
                {"type": "shipment", "shipmentId": 301},
            ]
        ),
    )

    first = await aggregator.collect(ticket)
    assert len(first) == 4
    assert call_counter["/orders/101"] == 1
    assert any(entry["type"] == "order" for entry in first)

    second = await aggregator.collect(ticket)
    assert second == first
    assert call_counter["/orders/101"] == 1  # cached

    await aggregator.invalidate(ticket.id)

    third = await aggregator.collect(ticket)
    assert third == first
    assert call_counter["/orders/101"] == 2

    await aggregator.close()
    await redis.close()

    assert miss_tracker.delta() >= 2
    assert hit_tracker.delta() == 1
    assert write_tracker.delta() == 2
    assert invalidate_tracker.delta() == 1
    assert remote_count_tracker.delta() == 2
    assert cache_count_tracker.delta() == 1
    assert failure_tracker.delta() == 0


@pytest.mark.asyncio
async def test_timeline_aggregator_handles_http_errors() -> None:
    def handler(_: Request) -> Response:
        return Response(500)

    client = AsyncClient(transport=MockTransport(handler))
    aggregator = TimelineAggregator(
        client=client,
        redis=None,
        cache_ttl=60,
        order_base_url="http://order.local",
        payment_base_url="http://payment.local",
        fulfillment_base_url="http://fulfillment.local",
    )

    ticket = SupportTicket(
        id="ticket-err",
        subject="Order investigation",
        description=None,
        customer_id="cust-2",
        status="open",
        priority="normal",
        channel="email",
        assigned_agent_id=None,
        context_json=json.dumps([{"type": "order", "orderId": 202}]),
    )
    http_failure_tracker = _MetricTracker(
        "support_timeline_collection_failures_total",
        {"stage": "http"},
    )

    entries = await aggregator.collect(ticket)
    assert entries == []
    assert http_failure_tracker.delta() >= 1

    await aggregator.close()


@pytest.mark.asyncio
async def test_timeline_aggregator_handles_cache_errors() -> None:
    call_counter: Counter[str] = Counter()

    def handler(request: Request) -> Response:
        call_counter[str(request.url.path)] += 1
        if request.url.path.endswith("/orders/707"):
            payload = {
                "id": 707,
                "status": "processing",
                "grandTotal": "59.95",
                "updatedAt": "2025-01-06T09:00:00+00:00",
            }
            return Response(200, json=payload)
        return Response(404)

    transport = MockTransport(handler)
    client = AsyncClient(transport=transport)
    redis_stub = _ErrorRedis()
    redis = cast(RedisType, redis_stub)

    aggregator = TimelineAggregator(
        client=client,
        redis=redis,
        cache_ttl=120,
        order_base_url="http://order.local",
        payment_base_url=None,
        fulfillment_base_url=None,
    )

    miss_tracker = _MetricTracker("support_timeline_cache_events_total", {"event": "miss"})
    error_tracker = _MetricTracker("support_timeline_cache_events_total", {"event": "error"})
    cache_failure_tracker = _MetricTracker(
        "support_timeline_collection_failures_total",
        {"stage": "cache"},
    )
    remote_count_tracker = _MetricTracker(
        "support_timeline_collect_seconds_count",
        {"source": "remote"},
    )
    cache_count_tracker = _MetricTracker(
        "support_timeline_collect_seconds_count",
        {"source": "cache"},
    )

    ticket = SupportTicket(
        id="ticket-cache-error",
        subject="Where is my order?",
        description=None,
        customer_id="cust-404",
        status="open",
        priority="normal",
        channel="chat",
        assigned_agent_id=None,
        context_json=json.dumps([{"type": "order", "orderId": 707}]),
    )

    first = await aggregator.collect(ticket)
    assert first
    assert call_counter["/orders/707"] == 1

    second = await aggregator.collect(ticket)
    assert second == first
    assert call_counter["/orders/707"] == 2

    await aggregator.invalidate(ticket.id)

    assert miss_tracker.delta() == 2
    assert error_tracker.delta() >= 5
    assert cache_failure_tracker.delta() >= 5
    assert remote_count_tracker.delta() == 2
    assert cache_count_tracker.delta() == 0

    assert redis_stub.get_calls == 2
    assert redis_stub.set_calls == 2
    assert redis_stub.delete_calls == 1

    await aggregator.close()


@pytest.mark.asyncio
async def test_timeline_aggregator_recovers_from_corrupted_cache() -> None:
    call_counter: Counter[str] = Counter()

    def handler(request: Request) -> Response:
        call_counter[str(request.url.path)] += 1
        if request.url.path.endswith("/orders/303"):
            payload = {
                "id": 303,
                "status": "processing",
                "grandTotal": "89.90",
                "updatedAt": "2025-01-05T09:15:00+00:00",
            }
            return Response(200, json=payload)
        return Response(404)

    transport = MockTransport(handler)
    client = AsyncClient(transport=transport)
    redis_stub = _MemoryRedis()
    cache_key = TimelineAggregator._cache_key("ticket-corrupt")
    redis_stub._store[cache_key] = "not-json"  # type: ignore[attr-defined]

    aggregator = TimelineAggregator(
        client=client,
        redis=cast(RedisType, redis_stub),
        cache_ttl=60,
        order_base_url="http://order.local",
        payment_base_url=None,
        fulfillment_base_url=None,
    )

    miss_tracker = _MetricTracker("support_timeline_cache_events_total", {"event": "miss"})
    write_tracker = _MetricTracker("support_timeline_cache_events_total", {"event": "write"})
    cache_count_tracker = _MetricTracker(
        "support_timeline_collect_seconds_count",
        {"source": "cache"},
    )
    cache_failure_tracker = _MetricTracker(
        "support_timeline_collection_failures_total",
        {"stage": "cache_decode"},
    )
    remote_count_tracker = _MetricTracker(
        "support_timeline_collect_seconds_count",
        {"source": "remote"},
    )

    ticket = SupportTicket(
        id="ticket-corrupt",
        subject="Status update",
        description=None,
        customer_id="cust-9",
        status="open",
        priority="normal",
        channel="email",
        assigned_agent_id=None,
        context_json=json.dumps([{"type": "order", "orderId": 303}]),
    )

    entries = await aggregator.collect(ticket)
    assert entries
    assert call_counter["/orders/303"] == 1

    cached_value = await redis_stub.get(cache_key)
    assert cached_value is not None
    assert json.loads(cached_value) == entries

    assert miss_tracker.delta() == 1
    assert cache_failure_tracker.delta() == 1
    assert remote_count_tracker.delta() == 1
    assert write_tracker.delta() == 1
    assert cache_count_tracker.delta() == 0

    await aggregator.close()
    await redis_stub.close()