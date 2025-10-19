"""Timeline aggregation helpers for the support service."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from time import perf_counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol, Sequence

import httpx

from services.common.cache import RedisType

from .metrics import (
    SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL,
    SUPPORT_TIMELINE_COLLECT_SECONDS,
    SUPPORT_TIMELINE_COLLECTION_FAILURES_TOTAL,
)
from .models import SupportTicket


class TimelineAggregatorProtocol(Protocol):
    async def collect(self, ticket: SupportTicket) -> list[dict[str, Any]]:
        ...

    async def invalidate(self, ticket_id: str) -> None:
        ...


@dataclass(slots=True)
class _TimelineReferences:
    """IDs discovered from ticket context for downstream lookups."""

    order_id: int | None = None
    payment_ids: set[int] = field(default_factory=set)
    shipment_ids: set[int] = field(default_factory=set)


def _normalize_base(url: str | None) -> str | None:
    if not url:
        return None
    return url.rstrip("/")


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = "".join(ch for ch in value if ch.isdigit())
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:  # pragma: no cover - defensive guard
            return None
    return None


def _normalize_timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _parse_context(context_json: str | None) -> list[dict[str, Any]]:
    if not context_json:
        return []
    try:
        parsed = json.loads(context_json)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [entry for entry in parsed if isinstance(entry, dict)]
    return []


def _extract_references(context: Iterable[dict[str, Any]]) -> _TimelineReferences:
    references = _TimelineReferences()
    for entry in context:
        entry_type = str(entry.get("type", "")).lower()
        if entry_type == "order":
            candidate = _coerce_int(entry.get("orderId") or entry.get("id"))
            if candidate is not None:
                references.order_id = candidate
        elif entry_type == "payment":
            candidate = _coerce_int(entry.get("paymentId") or entry.get("id"))
            if candidate is not None:
                references.payment_ids.add(candidate)
        elif entry_type == "shipment":
            candidate = _coerce_int(entry.get("shipmentId") or entry.get("id"))
            if candidate is not None:
                references.shipment_ids.add(candidate)
    return references


class TimelineAggregator:
    """Collects downstream service data to enrich support ticket timelines."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        redis: RedisType | None,
        cache_ttl: int,
        order_base_url: str | None,
        payment_base_url: str | None,
        fulfillment_base_url: str | None,
    ) -> None:
        self._client = client
        self._redis = redis
        self._cache_ttl = cache_ttl
        self._order_base_url = _normalize_base(order_base_url)
        self._payment_base_url = _normalize_base(payment_base_url)
        self._fulfillment_base_url = _normalize_base(fulfillment_base_url)

    async def close(self) -> None:
        await self._client.aclose()

    async def collect(self, ticket: SupportTicket) -> list[dict[str, Any]]:
        cache_key = self._cache_key(ticket.id)
        cache_start = perf_counter()
        if self._redis is not None and self._cache_ttl > 0:
            cached: str | None = None
            try:
                cached = await self._redis.get(cache_key)
            except Exception:
                SUPPORT_TIMELINE_COLLECTION_FAILURES_TOTAL.labels(stage="cache").inc()
                SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL.labels(event="error").inc()
                SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL.labels(event="miss").inc()
            else:
                if cached:
                    try:
                        data = json.loads(cached)
                    except json.JSONDecodeError:
                        SUPPORT_TIMELINE_COLLECTION_FAILURES_TOTAL.labels(stage="cache_decode").inc()
                        with suppress(Exception):
                            await self._redis.delete(cache_key)
                        SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL.labels(event="miss").inc()
                    else:
                        SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL.labels(event="hit").inc()
                        SUPPORT_TIMELINE_COLLECT_SECONDS.labels(source="cache").observe(
                            perf_counter() - cache_start
                        )
                        return data
                else:
                    SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL.labels(event="miss").inc()

        remote_start = perf_counter()
        entries = await self._build_entries(ticket)
        SUPPORT_TIMELINE_COLLECT_SECONDS.labels(source="remote").observe(
            perf_counter() - remote_start
        )
        if self._redis is not None and self._cache_ttl > 0:
            try:
                await self._redis.set(cache_key, json.dumps(entries, default=str), ex=self._cache_ttl)
            except Exception:
                SUPPORT_TIMELINE_COLLECTION_FAILURES_TOTAL.labels(stage="cache").inc()
                SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL.labels(event="error").inc()
            else:
                SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL.labels(event="write").inc()
        return entries

    async def invalidate(self, ticket_id: str) -> None:
        if self._redis is None or self._cache_ttl <= 0:
            return
        try:
            await self._redis.delete(self._cache_key(ticket_id))
        except Exception:
            SUPPORT_TIMELINE_COLLECTION_FAILURES_TOTAL.labels(stage="cache").inc()
            SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL.labels(event="error").inc()
            return
        SUPPORT_TIMELINE_CACHE_EVENTS_TOTAL.labels(event="invalidate").inc()

    async def _build_entries(self, ticket: SupportTicket) -> list[dict[str, Any]]:
        context_entries = _parse_context(ticket.context_json)
        references = _extract_references(context_entries)
        tasks = []
        if references.order_id is not None and self._order_base_url:
            tasks.append(self._fetch_order_data(references.order_id))
        if self._payment_base_url:
            if references.payment_ids:
                tasks.append(self._fetch_payments_by_ids(sorted(references.payment_ids)))
            elif references.order_id is not None:
                tasks.append(self._fetch_payments_for_order(references.order_id))
        if self._fulfillment_base_url:
            if references.shipment_ids:
                tasks.append(self._fetch_shipments_by_ids(sorted(references.shipment_ids)))
            elif references.order_id is not None:
                tasks.append(self._fetch_shipments_for_order(references.order_id))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        aggregated: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, Exception) or result is None:
                SUPPORT_TIMELINE_COLLECTION_FAILURES_TOTAL.labels(stage="aggregate").inc()
                continue
            if isinstance(result, list):
                aggregated.extend(result)
        return aggregated

    async def _fetch_order_data(self, order_id: int) -> list[dict[str, Any]]:
        if not self._order_base_url:
            return []
        entries: list[dict[str, Any]] = []
        order = await self._get_json(self._build_url(self._order_base_url, f"/orders/{order_id}"))
        if isinstance(order, dict):
            entries.append(
                {
                    "source": "order-service",
                    "type": "order",
                    "orderId": order.get("id"),
                    "status": order.get("status"),
                    "total": order.get("grandTotal"),
                    "timestamp": _normalize_timestamp(order.get("updatedAt") or order.get("createdAt")),
                }
            )
        events = await self._get_json(
            self._build_url(self._order_base_url, f"/orders/{order_id}/events")
        )
        if isinstance(events, list):
            for event in events:
                if isinstance(event, dict):
                    entries.append(
                        {
                            "source": "order-service",
                            "type": "order-event",
                            "eventType": event.get("type"),
                            "payload": event.get("payload"),
                            "timestamp": _normalize_timestamp(event.get("createdAt")),
                        }
                    )
        return entries

    async def _fetch_payments_by_ids(self, payment_ids: Sequence[int]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if not self._payment_base_url:
            return entries
        for payment_id in payment_ids:
            payload = await self._get_json(
                self._build_url(self._payment_base_url, f"/payments/{payment_id}")
            )
            if isinstance(payload, dict):
                entries.append(self._format_payment(payload))
        return entries

    async def _fetch_payments_for_order(self, order_id: int) -> list[dict[str, Any]]:
        if not self._payment_base_url:
            return []
        payload = await self._get_json(
            self._build_url(self._payment_base_url, "/payments"),
            params={"orderId": order_id, "limit": 50},
        )
        if not isinstance(payload, dict):
            return []
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        return [self._format_payment(item) for item in items if isinstance(item, dict)]

    async def _fetch_shipments_by_ids(self, shipment_ids: Sequence[int]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if not self._fulfillment_base_url:
            return entries
        for shipment_id in shipment_ids:
            payload = await self._get_json(
                self._build_url(self._fulfillment_base_url, f"/fulfillment/shipments/{shipment_id}")
            )
            if isinstance(payload, dict):
                entries.append(self._format_shipment(payload))
        return entries

    async def _fetch_shipments_for_order(self, order_id: int) -> list[dict[str, Any]]:
        if not self._fulfillment_base_url:
            return []
        payload = await self._get_json(
            self._build_url(self._fulfillment_base_url, "/fulfillment/shipments"),
            params={"orderId": order_id, "limit": 50},
        )
        if not isinstance(payload, dict):
            return []
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        return [self._format_shipment(item) for item in items if isinstance(item, dict)]

    def _format_payment(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": "payment-service",
            "type": "payment",
            "paymentId": data.get("id"),
            "orderId": data.get("orderId"),
            "status": data.get("status"),
            "amount": data.get("amount"),
            "timestamp": _normalize_timestamp(data.get("updatedAt") or data.get("createdAt")),
        }

    def _format_shipment(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": "fulfillment-service",
            "type": "shipment",
            "shipmentId": data.get("id"),
            "orderId": data.get("orderId"),
            "status": data.get("status"),
            "trackingNumber": data.get("trackingNumber"),
            "timestamp": _normalize_timestamp(data.get("updatedAt") or data.get("createdAt")),
        }

    async def _get_json(
        self, url: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            SUPPORT_TIMELINE_COLLECTION_FAILURES_TOTAL.labels(stage="http").inc()
            return None

    @staticmethod
    def _build_url(base: str, path: str) -> str:
        return f"{base}/{path.lstrip('/')}"

    @staticmethod
    def _cache_key(ticket_id: str) -> str:
        return f"support:timeline:{ticket_id}"