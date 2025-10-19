"""Event publishing helpers for the support service."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from services.common.kafka import KafkaProducerStub

from .models import SupportAttachment, SupportConversation, SupportTicket


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_context(context_json: str | None) -> Any:
    if not context_json:
        return None
    try:
        return json.loads(context_json)
    except json.JSONDecodeError:
        return None


def _ticket_payload(ticket: SupportTicket) -> dict[str, Any]:
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "description": ticket.description,
        "customerId": ticket.customer_id,
        "status": ticket.status,
        "priority": ticket.priority,
        "channel": ticket.channel,
        "assignedAgentId": ticket.assigned_agent_id,
        "context": _parse_context(ticket.context_json),
        "createdAt": _iso(ticket.created_at),
        "updatedAt": _iso(ticket.updated_at),
    }


def _conversation_payload(conversation: SupportConversation | None) -> dict[str, Any] | None:
    if conversation is None:
        return None
    return {
        "id": conversation.id,
        "ticketId": conversation.ticket_id,
        "authorType": conversation.author_type,
        "message": conversation.message,
        "attachmentUri": conversation.attachment_uri,
        "sentiment": conversation.sentiment,
        "metadata": None if conversation.metadata_json is None else _parse_context(conversation.metadata_json),
        "createdAt": _iso(conversation.created_at),
    }


def _attachment_payload(attachment: SupportAttachment) -> dict[str, Any]:
    return {
        "id": attachment.id,
        "ticketId": attachment.ticket_id,
        "filename": attachment.filename,
        "contentType": attachment.content_type,
        "sizeBytes": attachment.size_bytes,
        "uri": attachment.uri,
        "storagePath": attachment.storage_path,
        "createdAt": _iso(attachment.created_at),
    }


class SupportEventPublisher:
    """Publishes support case domain events via the configured Kafka producer."""

    def __init__(self, producer: KafkaProducerStub | None) -> None:
        self._producer = producer

    async def _emit(self, topic: str, payload: dict[str, Any]) -> None:
        if self._producer is None:
            return
        envelope = {
            "eventType": topic,
            "occurredAt": _now_iso(),
            **payload,
        }
        await self._producer.send(topic, envelope)

    async def case_opened(
        self,
        ticket: SupportTicket,
        initial_message: SupportConversation | None,
    ) -> None:
        await self._emit(
            "support.case.opened.v1",
            {
                "ticket": _ticket_payload(ticket),
                "initialMessage": _conversation_payload(initial_message),
            },
        )

    async def conversation_added(
        self,
        ticket: SupportTicket,
        conversation: SupportConversation,
    ) -> None:
        await self._emit(
            "support.case.updated.v1",
            {
                "ticket": _ticket_payload(ticket),
                "changeType": "conversation.added",
                "conversation": _conversation_payload(conversation),
            },
        )

    async def status_changed(
        self,
        ticket: SupportTicket,
        previous_status: str,
    ) -> None:
        change_payload = {
            "ticket": _ticket_payload(ticket),
            "changeType": "status.changed",
            "previousStatus": previous_status,
            "currentStatus": ticket.status,
        }
        await self._emit("support.case.updated.v1", change_payload)
        if ticket.status.lower() == "closed":
            await self._emit(
                "support.case.closed.v1",
                {
                    "ticket": _ticket_payload(ticket),
                    "previousStatus": previous_status,
                },
            )

    async def attachment_added(
        self,
        ticket: SupportTicket,
        attachment: SupportAttachment,
    ) -> None:
        await self._emit(
            "support.case.updated.v1",
            {
                "ticket": _ticket_payload(ticket),
                "changeType": "attachment.added",
                "attachment": _attachment_payload(attachment),
            },
        )