"""Event publishing helpers for the notification service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from services.common.kafka import KafkaProducerStub

from .models import Notification


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _mask_recipient(recipient: str) -> str:
    if "@" not in recipient:
        return recipient
    name, domain = recipient.split("@", 1)
    if len(name) <= 2:
        masked_name = name[0] + "*"
    else:
        masked_name = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked_name}@{domain}"


class NotificationEventPublisher:
    """Publishes notification lifecycle events."""

    def __init__(self, producer: KafkaProducerStub | None) -> None:
        self._producer = producer

    async def _emit(self, topic: str, payload: dict[str, Any]) -> None:
        if self._producer is None:
            return
        envelope = {
            "eventType": topic,
            "occurredAt": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        await self._producer.send(topic, envelope)

    async def notification_sent(self, notification: Notification) -> None:
        await self._emit(
            "notification.sent.v1",
            {
                "notification": self._serialize_notification(notification),
                "status": notification.status,
            },
        )

    async def notification_failed(self, notification: Notification, reason: str) -> None:
        await self._emit(
            "notification.failed.v1",
            {
                "notification": self._serialize_notification(notification),
                "status": notification.status,
                "reason": reason,
            },
        )

    async def preferences_updated(self, *, customer_id: int, preferences: Sequence[dict[str, Any]] | None) -> None:
        await self._emit(
            "notification.preference.updated.v1",
            {
                "customerId": customer_id,
                "preferences": list(preferences or []),
            },
        )

    def _serialize_notification(self, notification: Notification) -> dict[str, Any]:
        return {
            "id": notification.id,
            "channel": notification.channel,
            "recipient": _mask_recipient(notification.recipient),
            "template": notification.template,
            "sendAfter": _iso(notification.send_after),
            "sentAt": _iso(notification.sent_at),
            "createdAt": _iso(notification.created_at),
            "updatedAt": _iso(notification.updated_at),
        }
