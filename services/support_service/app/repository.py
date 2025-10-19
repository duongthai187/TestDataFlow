"""Database helpers for support service operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import SupportAttachment, SupportConversation, SupportTicket


class SupportRepository:
    """Persistence helpers for support tickets and conversations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_ticket(
        self,
        *,
        subject: str,
        description: str | None,
        customer_id: str | None,
        channel: str,
        priority: str,
        assigned_agent_id: str | None,
        context: dict[str, Any] | list[dict[str, Any]] | None,
    ) -> SupportTicket:
        ticket = SupportTicket(
            subject=subject,
            description=description,
            customer_id=customer_id,
            channel=channel,
            priority=priority,
            assigned_agent_id=assigned_agent_id,
            context_json=json.dumps(context, default=str) if context is not None else None,
        )
        self.session.add(ticket)
        await self.session.flush()
        await self.session.refresh(ticket, attribute_names=["created_at", "updated_at"])
        return ticket

    async def set_context(
        self,
        ticket: SupportTicket,
        context: dict[str, Any] | list[dict[str, Any]] | None,
    ) -> SupportTicket:
        ticket.context_json = json.dumps(context, default=str) if context is not None else None
        await self.session.flush()
        await self.session.refresh(ticket, attribute_names=["updated_at"])
        return ticket

    async def add_conversation(
        self,
        ticket: SupportTicket,
        *,
        author_type: str,
        message: str,
        attachment_uri: str | None,
        sentiment: str | None,
        metadata: dict[str, Any] | None,
        created_at: datetime | None = None,
    ) -> SupportConversation:
        conversation = SupportConversation(
            ticket=ticket,
            author_type=author_type,
            message=message,
            attachment_uri=attachment_uri,
            sentiment=sentiment,
            metadata_json=json.dumps(metadata, default=str) if metadata is not None else None,
            created_at=created_at,
        )
        self.session.add(conversation)
        await self.session.flush()
        await self.session.refresh(conversation)
        await self.session.refresh(ticket, attribute_names=["updated_at"])
        return conversation

    async def get_ticket(self, ticket_id: str) -> SupportTicket | None:
        result = await self.session.execute(
            select(SupportTicket)
            .options(
                selectinload(SupportTicket.conversations),
                selectinload(SupportTicket.attachments),
            )
            .where(SupportTicket.id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def list_tickets(
        self,
        *,
        customer_id: str | None,
        status: str | None,
        agent_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[SupportTicket], int]:
        filters = []
        if customer_id is not None:
            filters.append(SupportTicket.customer_id == customer_id)
        if status is not None:
            filters.append(SupportTicket.status == status)
        if agent_id is not None:
            filters.append(SupportTicket.assigned_agent_id == agent_id)

        base: Select[tuple[SupportTicket]] = select(SupportTicket).order_by(SupportTicket.created_at.desc())
        count: Select[tuple[int]] = select(func.count(SupportTicket.id))

        if filters:
            clause = and_(*filters)
            base = base.where(clause)
            count = count.where(clause)

        total = (await self.session.execute(count)).scalar_one()
        result = await self.session.execute(base.offset(offset).limit(limit))
        return list(result.scalars().unique()), total

    async def update_status(
        self,
        ticket: SupportTicket,
        *,
        status: str,
        assigned_agent_id: str | None,
    ) -> SupportTicket:
        ticket.status = status
        ticket.assigned_agent_id = assigned_agent_id
        await self.session.flush()
        await self.session.refresh(ticket, attribute_names=["updated_at", "status", "assigned_agent_id"])
        return ticket

    async def get_agent_workload(self, agent_id: str) -> dict[str, int]:
        result = await self.session.execute(
            select(SupportTicket.status, func.count(SupportTicket.id)).where(SupportTicket.assigned_agent_id == agent_id).group_by(SupportTicket.status)
        )
        counters = {status: count for status, count in result.all()}
        return {
            "open": counters.get("open", 0),
            "pending": counters.get("pending", 0),
            "resolved": counters.get("resolved", 0),
            "closed": counters.get("closed", 0),
        }

    async def add_attachment(
        self,
        ticket: SupportTicket,
        *,
        filename: str,
        content_type: str,
        size_bytes: int,
        storage_path: str,
        uri: str,
    ) -> SupportAttachment:
        attachment = SupportAttachment(
            ticket=ticket,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            uri=uri,
        )
        self.session.add(attachment)
        await self.session.flush()
        await self.session.refresh(attachment)
        await self.session.refresh(ticket, attribute_names=["updated_at"])
        return attachment

    async def list_attachments(self, ticket_id: str) -> list[SupportAttachment]:
        result = await self.session.execute(
            select(SupportAttachment)
            .where(SupportAttachment.ticket_id == ticket_id)
            .order_by(SupportAttachment.created_at)
        )
        return list(result.scalars().unique())

    async def find_tickets_by_references(
        self,
        *,
        order_reference: str | None = None,
        shipment_reference: str | None = None,
    ) -> list[SupportTicket]:
        if not order_reference and not shipment_reference:
            return []

        stmt = (
            select(SupportTicket)
            .options(
                selectinload(SupportTicket.conversations),
                selectinload(SupportTicket.attachments),
            )
            .where(SupportTicket.status != "closed")
        )

        if order_reference and shipment_reference:
            stmt = stmt.where(
                or_(
                    SupportTicket.context_json.contains(order_reference),
                    SupportTicket.context_json.contains(shipment_reference),
                )
            )
        elif order_reference:
            stmt = stmt.where(SupportTicket.context_json.contains(order_reference))
        elif shipment_reference:
            stmt = stmt.where(SupportTicket.context_json.contains(shipment_reference))

        result = await self.session.execute(stmt)
        return list(result.scalars().unique())