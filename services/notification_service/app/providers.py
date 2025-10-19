"""Notification provider implementations used by the service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List


@dataclass(slots=True)
class SentNotification:
    recipient: str
    channel: str
    subject: str | None
    body: str
    metadata: dict[str, Any] | None


class InMemoryNotificationProvider:
    """Simple provider storing sent notifications for inspection during tests."""

    def __init__(self) -> None:
        self.sent: List[SentNotification] = []

    async def send(
        self,
        *,
        recipient: str,
        channel: str,
        subject: str | None,
        body: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        self.sent.append(
            SentNotification(
                recipient=recipient,
                channel=channel,
                subject=subject,
                body=body,
                metadata=metadata,
            )
        )
