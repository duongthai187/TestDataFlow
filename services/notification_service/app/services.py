"""Service layer for notification operations."""

from __future__ import annotations

import json
import string
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Protocol, Sequence, cast

from .events import NotificationEventPublisher
from .models import Notification, NotificationJob, NotificationTemplate
from .repository import NotificationRepository
from .schemas import (
    BatchNotificationRequest,
    BatchRecipient,
    NotificationCreate,
    PreferenceEntry,
    TemplateCreate,
    TemplateFilters,
    TemplateUpdate,
)
from .metrics import (
    NOTIFICATION_FAILURE_TOTAL,
    NOTIFICATION_PREFERENCE_UPDATES_TOTAL,
    NOTIFICATION_RATE_LIMIT_TOTAL,
    NOTIFICATION_SEND_LATENCY_SECONDS,
    NOTIFICATION_SENT_TOTAL,
)


class NotificationProvider(Protocol):
    async def send(
        self,
        *,
        recipient: str,
        channel: str,
        subject: str | None,
        body: str,
        metadata: dict[str, Any] | None,
    ) -> None: ...


def _metadata_to_json(metadata: dict[str, Any] | None) -> str | None:
    if metadata is None:
        return None
    return json.dumps(metadata, separators=(",", ":"), ensure_ascii=False)


def metadata_from_json(metadata_json: str | None) -> dict[str, Any] | None:
    if metadata_json is None:
        return None
    return json.loads(metadata_json)


class RateLimitExceeded(Exception):
    """Raised when a channel exceeds its rate limit."""


class NotificationService:
    """High-level orchestration for notifications."""

    def __init__(
        self,
        repository: NotificationRepository,
        provider: NotificationProvider | None = None,
        rate_limiter: object | None = None,
        event_publisher: NotificationEventPublisher | None = None,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.rate_limiter = rate_limiter if hasattr(rate_limiter, "allow") else None
        self.event_publisher = event_publisher

    async def create_notification(self, payload: NotificationCreate) -> Notification:
        notification = await self.repository.create_notification(
            recipient=payload.recipient,
            channel=payload.channel,
            subject=payload.subject,
            body=payload.body,
            template=payload.template,
            metadata_json=_metadata_to_json(payload.metadata),
            send_after=payload.send_after,
        )
        await self.repository.add_event(notification, event_type="created", payload=notification.status)
        return notification

    async def send_notification(self, notification: Notification) -> Notification:
        start_time = monotonic()
        await self._enforce_rate_limit(notification.channel, amount=1)
        if self.provider:
            await self.provider.send(
                recipient=notification.recipient,
                channel=notification.channel,
                subject=notification.subject,
                body=notification.body,
                metadata=metadata_from_json(notification.metadata_json),
            )
        sent_at = datetime.now(tz=timezone.utc)
        await self.repository.add_event(notification, event_type="sent", payload=sent_at.isoformat())
        updated = await self.repository.update_status(
            notification,
            status="sent",
            sent_at=sent_at,
            error_message=None,
        )
        await self._publish_sent(updated)
        duration = monotonic() - start_time
        NOTIFICATION_SENT_TOTAL.labels(channel=notification.channel).inc()
        NOTIFICATION_SEND_LATENCY_SECONDS.labels(channel=notification.channel).observe(duration)
        return updated

    async def fail_notification(self, notification: Notification, *, reason: str) -> Notification:
        await self.repository.add_event(notification, event_type="failed", payload=reason)
        updated = await self.repository.update_status(
            notification,
            status="failed",
            sent_at=None,
            error_message=reason,
        )
        await self._publish_failed(updated, reason)
        NOTIFICATION_FAILURE_TOTAL.labels(channel=notification.channel).inc()
        return updated

    async def reschedule_notification(
        self,
        notification: Notification,
        *,
        send_after: datetime | None,
    ) -> Notification:
        payload = send_after.isoformat() if send_after else "cleared"
        await self.repository.add_event(notification, event_type="rescheduled", payload=payload)
        return await self.repository.reschedule(notification, send_after=send_after)

    async def update_metadata(self, notification: Notification, metadata: dict[str, Any] | None) -> Notification:
        notification.metadata_json = _metadata_to_json(metadata)
        await self.repository.session.flush()
        await self.repository.session.refresh(notification, attribute_names=["updated_at"])
        await self.repository.add_event(notification, event_type="metadata_updated", payload="updated")
        return notification

    async def get_preferences(self, customer_id: int) -> list[PreferenceEntry]:
        preferences = await self.repository.get_preferences(customer_id)
        preferences.sort(key=lambda pref: pref.channel)
        return [self._to_entry(preference) for preference in preferences]

    async def update_preferences(self, customer_id: int, entries: list[PreferenceEntry]) -> list[PreferenceEntry]:
        payload = {entry.channel: entry.opt_in for entry in entries}
        await self.repository.upsert_preferences(customer_id, payload)
        updated = await self.get_preferences(customer_id)
        await self._publish_preferences_updated(customer_id, updated)
        for entry in updated:
            NOTIFICATION_PREFERENCE_UPDATES_TOTAL.labels(channel=entry.channel).inc()
        return updated

    @staticmethod
    def _to_entry(preference) -> PreferenceEntry:
        return PreferenceEntry(
            channel=preference.channel,
            optIn=preference.opt_in,
            updatedAt=preference.updated_at,
        )

    async def create_template(self, payload: TemplateCreate) -> NotificationTemplate:
        return await self.repository.create_template(
            name=payload.name,
            channel=payload.channel,
            locale=payload.locale,
            version=payload.version,
            subject=payload.subject,
            body=payload.body,
            metadata_json=_metadata_to_json(payload.metadata),
        )

    async def list_templates(
        self,
        filters: TemplateFilters,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationTemplate], int]:
        return await self.repository.list_templates(
            name=filters.name,
            channel=filters.channel,
            locale=filters.locale,
            limit=limit,
            offset=offset,
        )

    async def update_template(
        self,
        template: NotificationTemplate,
        payload: TemplateUpdate,
    ) -> NotificationTemplate:
        updates = payload.model_dump(exclude_unset=True)
        if "metadata" in updates:
            metadata_json = _metadata_to_json(updates.pop("metadata"))
            updates["metadata_json"] = metadata_json
        return await self.repository.update_template(template, updates)

    async def schedule_batch(self, payload: BatchNotificationRequest) -> NotificationJob:
        template = await self.repository.get_template(payload.template_id)
        if template is None:
            raise ValueError("template_not_found")

        recipients = payload.recipients
        if not recipients:
            raise ValueError("empty_batch")

        await self._enforce_rate_limit(template.channel, amount=len(recipients))

        job = await self.repository.create_job(
            template_id=template.id,
            status="processing",
            scheduled_for=payload.scheduled_for,
            total_count=len(recipients),
            payload_json=None,
        )

        base_metadata = metadata_from_json(template.metadata_json) or {}

        rendered_notifications = self._render_notifications(
            template=template,
            recipients=recipients,
            base_metadata=base_metadata,
            scheduled_for=payload.scheduled_for,
            job_id=job.id,
        )
        for rendered in rendered_notifications:
            await self.repository.create_notification(**rendered)

        await self.repository.update_job(
            job,
            status="completed",
            processed_count=len(recipients),
        )
        return job

    async def list_jobs(
        self,
        *,
        status: str | None,
        template_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationJob], int]:
        return await self.repository.list_jobs(
            status=status,
            template_id=template_id,
            limit=limit,
            offset=offset,
        )

    async def get_job(self, job_id: int) -> NotificationJob | None:
        return await self.repository.get_job(job_id)

    def _render_notifications(
        self,
        *,
        template: NotificationTemplate,
        recipients: Sequence[BatchRecipient],
        base_metadata: dict[str, Any],
        scheduled_for: datetime | None,
        job_id: int,
    ) -> list[dict[str, Any]]:
        rendered: list[dict[str, Any]] = []
        for entry in recipients:
            metadata = {**base_metadata, **(entry.metadata or {})}
            rendered.append(
                {
                    "recipient": entry.recipient,
                    "channel": template.channel,
                    "subject": self._format_value(template.subject, metadata),
                    "body": self._format_value(template.body, metadata),
                    "template": template.id,
                    "metadata_json": _metadata_to_json(metadata),
                    "send_after": scheduled_for,
                    "job_id": job_id,
                }
            )
        return rendered

    @staticmethod
    def _format_value(value: str | None, metadata: dict[str, Any]) -> str | None:
        if value is None:
            return None
        formatter = string.Formatter()
        safe_mapping = _SafeDict(metadata)
        try:
            return formatter.vformat(value, (), safe_mapping)
        except (KeyError, ValueError):
            return value

    async def _enforce_rate_limit(self, channel: str, *, amount: int) -> None:
        if amount <= 0 or self.rate_limiter is None:
            return
        limiter = cast(Any, self.rate_limiter)
        allowed = await limiter.allow(channel, amount=amount)
        if not allowed:
            NOTIFICATION_RATE_LIMIT_TOTAL.labels(channel=channel).inc()
            raise RateLimitExceeded(channel)

    async def _publish_sent(self, notification: Notification) -> None:
        if self.event_publisher is None:
            return
        await self.event_publisher.notification_sent(notification)

    async def _publish_failed(self, notification: Notification, reason: str) -> None:
        if self.event_publisher is None:
            return
        await self.event_publisher.notification_failed(notification, reason)

    async def _publish_preferences_updated(
        self,
        customer_id: int,
        preferences: list[PreferenceEntry],
    ) -> None:
        if self.event_publisher is None:
            return
        payload = [
            {
                "channel": entry.channel,
                "optIn": entry.opt_in,
                "updatedAt": entry.updated_at.isoformat() if entry.updated_at else None,
            }
            for entry in preferences
        ]
        await self.event_publisher.preferences_updated(customer_id=customer_id, preferences=payload)


class _SafeDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
