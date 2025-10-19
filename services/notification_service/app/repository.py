"""Persistence helpers for the notification service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import (
    Notification,
    NotificationEvent,
    NotificationJob,
    NotificationPreference,
    NotificationTemplate,
)


class NotificationRepository:
    """Database access helpers for notifications."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_notification(
        self,
        *,
        recipient: str,
        channel: str,
        subject: str | None,
        body: str,
        template: str | None,
        metadata_json: str | None,
        send_after: datetime | None,
        job_id: int | None = None,
    ) -> Notification:
        notification = Notification(
            recipient=recipient,
            channel=channel,
            subject=subject,
            body=body,
            template=template,
            metadata_json=metadata_json,
            send_after=send_after,
            job_id=job_id,
        )
        self.session.add(notification)
        await self.session.flush()
        await self.session.refresh(notification, attribute_names=["created_at", "updated_at"])
        return notification

    async def get_notification(self, notification_id: int) -> Notification | None:
        result = await self.session.execute(
            select(Notification)
            .options(selectinload(Notification.events))
            .where(Notification.id == notification_id)
        )
        return result.scalar_one_or_none()

    async def list_notifications(
        self,
        *,
        recipient: str | None,
        channel: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Notification], int]:
        filters = []
        if recipient is not None:
            filters.append(Notification.recipient == recipient)
        if channel is not None:
            filters.append(Notification.channel == channel)
        if status is not None:
            filters.append(Notification.status == status)

        base: Select[tuple[Notification]] = select(Notification).order_by(
            Notification.created_at.desc(), Notification.id.desc()
        )
        count: Select[tuple[int]] = select(func.count(Notification.id))

        if filters:
            clause = and_(*filters)
            base = base.where(clause)
            count = count.where(clause)

        total = (await self.session.execute(count)).scalar_one()
        result = await self.session.execute(
            base.offset(offset).limit(limit).options(selectinload(Notification.events))
        )
        notifications = list(result.scalars().unique())
        return notifications, total

    async def update_status(
        self,
        notification: Notification,
        *,
        status: str,
        sent_at: datetime | None = None,
        error_message: str | None = None,
    ) -> Notification:
        notification.status = status
        notification.sent_at = sent_at
        notification.error_message = error_message
        await self.session.flush()
        await self.session.refresh(notification, attribute_names=["updated_at", "sent_at"])
        return notification

    async def reschedule(self, notification: Notification, *, send_after: datetime | None) -> Notification:
        notification.send_after = send_after
        await self.session.flush()
        await self.session.refresh(notification, attribute_names=["updated_at", "send_after"])
        return notification

    async def add_event(
        self,
        notification: Notification,
        *,
        event_type: str,
        payload: str,
    ) -> NotificationEvent:
        event = NotificationEvent(notification=notification, type=event_type, payload=payload)
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def delete_notification(self, notification: Notification) -> None:
        await self.session.delete(notification)
        await self.session.flush()

    async def get_preferences(self, customer_id: int) -> list[NotificationPreference]:
        result = await self.session.execute(
            select(NotificationPreference).where(NotificationPreference.customer_id == customer_id)
        )
        return list(result.scalars())

    async def upsert_preferences(
        self,
        customer_id: int,
        preferences: dict[str, bool],
    ) -> list[NotificationPreference]:
        existing = await self.get_preferences(customer_id)
        existing_map = {preference.channel: preference for preference in existing}
        now = datetime.now(timezone.utc)
        updated: list[NotificationPreference] = []
        for channel, opt_in in preferences.items():
            entry = existing_map.get(channel)
            if entry is None:
                entry = NotificationPreference(
                    customer_id=customer_id,
                    channel=channel,
                    opt_in=opt_in,
                    updated_at=now,
                )
                self.session.add(entry)
            else:
                entry.opt_in = opt_in
                entry.updated_at = now
            updated.append(entry)
        await self.session.flush()
        for preference in updated:
            await self.session.refresh(preference)
        return updated

    async def create_template(
        self,
        *,
        name: str,
        channel: str,
        locale: str,
        version: int,
        subject: str | None,
        body: str,
        metadata_json: str | None,
    ) -> NotificationTemplate:
        template = NotificationTemplate(
            name=name,
            channel=channel,
            locale=locale,
            version=version,
            subject=subject,
            body=body,
            metadata_json=metadata_json,
        )
        self.session.add(template)
        await self.session.flush()
        await self.session.refresh(template, attribute_names=["created_at", "updated_at"])
        return template

    async def get_template(self, template_id: str) -> NotificationTemplate | None:
        result = await self.session.execute(
            select(NotificationTemplate).where(NotificationTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    async def list_templates(
        self,
        *,
        name: str | None,
        channel: str | None,
        locale: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationTemplate], int]:
        filters = []
        if name is not None:
            filters.append(NotificationTemplate.name == name)
        if channel is not None:
            filters.append(NotificationTemplate.channel == channel)
        if locale is not None:
            filters.append(NotificationTemplate.locale == locale)

        base: Select[tuple[NotificationTemplate]] = select(NotificationTemplate).order_by(
            NotificationTemplate.updated_at.desc(), NotificationTemplate.id
        )
        count: Select[tuple[int]] = select(func.count(NotificationTemplate.id))

        if filters:
            clause = and_(*filters)
            base = base.where(clause)
            count = count.where(clause)

        total = (await self.session.execute(count)).scalar_one()
        result = await self.session.execute(base.offset(offset).limit(limit))
        templates = list(result.scalars().unique())
        return templates, total

    async def update_template(self, template: NotificationTemplate, updates: dict[str, Any]) -> NotificationTemplate:
        for key, value in updates.items():
            setattr(template, key, value)
        await self.session.flush()
        await self.session.refresh(template, attribute_names=["updated_at"])
        return template

    async def delete_template(self, template: NotificationTemplate) -> None:
        await self.session.delete(template)
        await self.session.flush()

    async def create_job(
        self,
        *,
        template_id: str | None,
        status: str,
        scheduled_for: datetime | None,
        total_count: int,
        payload_json: str | None,
    ) -> NotificationJob:
        job = NotificationJob(
            template_id=template_id,
            status=status,
            scheduled_for=scheduled_for,
            total_count=total_count,
            processed_count=0,
            payload_json=payload_json,
        )
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job, attribute_names=["created_at", "updated_at"])
        return job

    async def get_job(self, job_id: int) -> NotificationJob | None:
        result = await self.session.execute(
            select(NotificationJob)
            .options(selectinload(NotificationJob.notifications))
            .where(NotificationJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        *,
        status: str | None,
        template_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationJob], int]:
        filters = []
        if status is not None:
            filters.append(NotificationJob.status == status)
        if template_id is not None:
            filters.append(NotificationJob.template_id == template_id)

        base: Select[tuple[NotificationJob]] = select(NotificationJob).order_by(
            NotificationJob.created_at.desc(), NotificationJob.id.desc()
        )
        count: Select[tuple[int]] = select(func.count(NotificationJob.id))

        if filters:
            clause = and_(*filters)
            base = base.where(clause)
            count = count.where(clause)

        total = (await self.session.execute(count)).scalar_one()
        result = await self.session.execute(
            base.offset(offset).limit(limit).options(selectinload(NotificationJob.notifications))
        )
        jobs = list(result.scalars().unique())
        return jobs, total

    async def update_job(
        self,
        job: NotificationJob,
        *,
        status: str | None = None,
        processed_count: int | None = None,
        error_message: str | None = None,
    ) -> NotificationJob:
        if status is not None:
            job.status = status
        if processed_count is not None:
            job.processed_count = processed_count
        job.error_message = error_message
        await self.session.flush()
        await self.session.refresh(job, attribute_names=["updated_at"])
        return job
