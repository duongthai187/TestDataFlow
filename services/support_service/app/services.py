"""Domain services for support operations."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import uuid4

from fastapi import UploadFile

from .events import SupportEventPublisher
from .metrics import (
    SUPPORT_CONVERSATION_ADDED_TOTAL,
    SUPPORT_TICKET_CREATED_TOTAL,
    SUPPORT_TICKET_STATUS_CHANGED_TOTAL,
    normalise_author,
    normalise_channel,
    normalise_status,
)
from .models import SupportAttachment, SupportConversation, SupportTicket
from .repository import SupportRepository
from .schemas import (
    AgentWorkloadResponse,
    AttachmentResponse,
    ConversationCreate,
    ConversationResponse,
    TicketCreate,
    TicketDetailResponse,
    TicketResponse,
    TicketCloseRequest,
)
from .storage import AttachmentStorageProtocol
from .timeline import TimelineAggregatorProtocol

_ALLOWED_STATUS = {"open", "pending", "resolved", "closed"}
_ALLOWED_PRIORITY = {"low", "normal", "high", "urgent"}
_ALLOWED_AUTHOR_TYPES = {"agent", "customer", "bot"}
_FILENAME_SANITIZE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def _normalize_priority(value: str | None) -> str:
    if value is None:
        return "normal"
    lowered = value.lower()
    return lowered if lowered in _ALLOWED_PRIORITY else "normal"


def _normalize_status(value: str | None) -> str:
    if value is None:
        return "open"
    lowered = value.lower()
    return lowered if lowered in _ALLOWED_STATUS else "open"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_json(value: str | None) -> object | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _sanitize_filename(filename: str | None) -> str:
    if not filename:
        return ""
    normalized = filename.replace("\\", "/").split("/")[-1]
    sanitized = _FILENAME_SANITIZE_PATTERN.sub("-", normalized.strip())
    sanitized = sanitized.lstrip(".")
    sanitized = sanitized.strip("-")
    if len(sanitized) > 255:
        sanitized = sanitized[:255]
    return sanitized


def _serialize_ticket(ticket: SupportTicket) -> dict[str, Any]:
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "description": ticket.description,
        "customerId": ticket.customer_id,
        "status": ticket.status,
        "priority": ticket.priority,
        "channel": ticket.channel,
        "assignedAgentId": ticket.assigned_agent_id,
        "context": _parse_json(ticket.context_json),
        "createdAt": _ensure_utc(ticket.created_at),
        "updatedAt": _ensure_utc(ticket.updated_at),
    }


def _conversation_to_dict(conversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "ticketId": conversation.ticket_id,
        "authorType": conversation.author_type,
        "message": conversation.message,
        "attachmentUri": conversation.attachment_uri,
        "sentiment": conversation.sentiment,
        "metadata": _parse_json(conversation.metadata_json),
        "createdAt": conversation.created_at,
    }


def _parse_timestamp(value: Any, default: datetime) -> datetime:
    if isinstance(value, datetime):
        ensured = _ensure_utc(value)
        return ensured if ensured is not None else _ensure_utc(default) or default
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            ensured = _ensure_utc(parsed)
            if ensured is not None:
                return ensured
        except ValueError:
            return _ensure_utc(default) or default
    ensured_default = _ensure_utc(default)
    return ensured_default if ensured_default is not None else default


def _attachment_entry(attachment: SupportAttachment, baseline: datetime) -> tuple[datetime, dict[str, Any]]:
    timestamp = _ensure_utc(getattr(attachment, "created_at", None))
    if timestamp is None:
        timestamp = baseline
    entry: dict[str, Any] = {
        "type": "attachment",
        "filename": attachment.filename,
        "uri": attachment.uri,
        "timestamp": timestamp.isoformat(),
    }
    return timestamp, entry


def _build_attachment_destination(ticket_id: str, filename: str | None) -> tuple[str, str]:
    sanitized = _sanitize_filename(filename)
    if not sanitized:
        sanitized = "attachment"
    unique = uuid4().hex[:8]
    stored_name = f"{unique}-{sanitized}"
    relative_path = f"support/cases/{ticket_id}/attachments/{stored_name}"
    return relative_path, sanitized


def _attachments_to_responses(
    attachments: Sequence[SupportAttachment] | None,
) -> list[AttachmentResponse]:
    if not attachments:
        return []
    return [AttachmentResponse.model_validate(attachment) for attachment in attachments]


def _build_timeline(
    ticket: SupportTicket,
    external_entries: Sequence[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    entries: list[tuple[datetime, dict[str, Any]]] = []
    created_at = _ensure_utc(ticket.created_at)
    baseline = created_at if created_at is not None else _now_utc()
    context = _parse_json(ticket.context_json)
    if isinstance(context, list):
        for entry in context:
            if isinstance(entry, dict):
                timestamp = _parse_timestamp(entry.get("timestamp"), baseline)
                normalized: dict[str, Any] = dict(entry)
                normalized["timestamp"] = timestamp.isoformat()
                entries.append((timestamp, normalized))
    elif isinstance(context, dict):
        timestamp = _parse_timestamp(context.get("timestamp"), baseline)
        normalized = dict(context)
        normalized["timestamp"] = timestamp.isoformat()
        entries.append((timestamp, normalized))

    for conversation in ticket.conversations:
        timestamp = _ensure_utc(conversation.created_at)
        if timestamp is None:
            timestamp = baseline
        entry: dict[str, Any] = {
            "type": "conversation",
            "authorType": conversation.author_type,
            "message": conversation.message,
            "attachmentUri": conversation.attachment_uri,
            "sentiment": conversation.sentiment,
            "metadata": _parse_json(conversation.metadata_json),
            "timestamp": timestamp.isoformat(),
        }
        entries.append((timestamp, entry))
    attachments = getattr(ticket, "attachments", [])
    for attachment in attachments:
        entries.append(_attachment_entry(attachment, baseline))
    if external_entries:
        for external in external_entries:
            timestamp = _parse_timestamp(external.get("timestamp"), baseline)
            entry = dict(external)
            entry["timestamp"] = timestamp.isoformat()
            entries.append((timestamp, entry))
    entries.sort(key=lambda item: item[0])
    return [entry for _, entry in entries]


class SupportService:
    """Application service orchestrating support workflows."""

    def __init__(
        self,
        repository: SupportRepository,
        timeline_aggregator: TimelineAggregatorProtocol | None = None,
        attachment_storage: AttachmentStorageProtocol | None = None,
        event_publisher: SupportEventPublisher | None = None,
    ) -> None:
        self.repository = repository
        self.timeline_aggregator = timeline_aggregator
        self.attachment_storage = attachment_storage
        self.event_publisher = event_publisher

    async def create_ticket(self, payload: TicketCreate) -> TicketDetailResponse:
        priority = _normalize_priority(payload.priority)
        ticket = await self.repository.create_ticket(
            subject=payload.subject,
            description=payload.description,
            customer_id=payload.customer_id,
            channel=payload.channel,
            priority=priority,
            assigned_agent_id=payload.assigned_agent_id,
            context=payload.context,
        )
        SUPPORT_TICKET_CREATED_TOTAL.labels(channel=normalise_channel(payload.channel)).inc()

        first_message = None
        if payload.initial_message is not None:
            author_type = payload.initial_message.author_type.lower()
            if author_type not in _ALLOWED_AUTHOR_TYPES:
                author_type = "customer"
            first_message = await self.repository.add_conversation(
                ticket,
                author_type=author_type,
                message=payload.initial_message.message,
                attachment_uri=payload.initial_message.attachment_uri,
                sentiment=payload.initial_message.sentiment,
                metadata=payload.initial_message.metadata,
                created_at=_now_utc(),
            )
            SUPPORT_CONVERSATION_ADDED_TOTAL.labels(
                author_type=normalise_author(author_type)
            ).inc()

        hydrated = await self.repository.get_ticket(ticket.id)
        if hydrated is None:
            hydrated = ticket

        serialized_ticket = _serialize_ticket(hydrated)
        messages = [
            ConversationResponse.model_validate(_conversation_to_dict(conversation))
            for conversation in hydrated.conversations
        ]
        attachments = _attachments_to_responses(getattr(hydrated, "attachments", []))
        await self._invalidate_timeline_cache(hydrated.id)
        await self._publish_case_opened(hydrated, first_message)
        return TicketDetailResponse.model_validate(
            {
                **serialized_ticket,
                "messages": messages,
                "timeline": _build_timeline(hydrated),
                "attachments": attachments,
            }
        )

    async def get_ticket(self, ticket: SupportTicket, include_timeline: bool) -> TicketDetailResponse:
        serialized_ticket = _serialize_ticket(ticket)
        messages = [ConversationResponse.model_validate(_conversation_to_dict(conversation)) for conversation in ticket.conversations]
        timeline: list[dict[str, object]] = []
        if include_timeline:
            external_entries: list[dict[str, Any]] = []
            if self.timeline_aggregator is not None:
                external_entries = await self.timeline_aggregator.collect(ticket)
            timeline = _build_timeline(ticket, external_entries=external_entries)
        attachments = _attachments_to_responses(getattr(ticket, "attachments", []))
        return TicketDetailResponse.model_validate(
            {
                **serialized_ticket,
                "messages": messages,
                "timeline": timeline,
                "attachments": attachments,
            }
        )

    async def add_message(self, ticket: SupportTicket, payload: ConversationCreate) -> ConversationResponse:
        author_type = payload.author_type.lower()
        if author_type not in _ALLOWED_AUTHOR_TYPES:
            author_type = "agent"
        conversation = await self.repository.add_conversation(
            ticket,
            author_type=author_type,
            message=payload.message,
            attachment_uri=payload.attachment_uri,
            sentiment=payload.sentiment,
            metadata=payload.metadata,
            created_at=_now_utc(),
        )
        SUPPORT_CONVERSATION_ADDED_TOTAL.labels(
            author_type=normalise_author(author_type)
        ).inc()
        await self._invalidate_timeline_cache(ticket.id)
        response = ConversationResponse.model_validate(_conversation_to_dict(conversation))
        await self._publish_conversation_added(ticket, conversation)
        return response

    async def update_status(
        self,
        ticket: SupportTicket,
        *,
        status: str,
        assigned_agent_id: str | None,
    ) -> TicketResponse:
        normalized_status = _normalize_status(status)
        previous_status = ticket.status
        updated = await self.repository.update_status(
            ticket,
            status=normalized_status,
            assigned_agent_id=assigned_agent_id,
        )
        SUPPORT_TICKET_STATUS_CHANGED_TOTAL.labels(
            status=normalise_status(normalized_status)
        ).inc()
        await self._invalidate_timeline_cache(ticket.id)
        response = TicketResponse.model_validate(_serialize_ticket(updated))
        await self._publish_status_changed(updated, previous_status)
        return response

    async def get_workload(self, agent_id: str) -> AgentWorkloadResponse:
        counters = await self.repository.get_agent_workload(agent_id)
        return AgentWorkloadResponse.model_validate(
            {
                "agentId": agent_id,
                "open": counters["open"],
                "pending": counters["pending"],
                "resolved": counters["resolved"],
                "closed": counters["closed"],
            }
        )

    async def _invalidate_timeline_cache(self, ticket_id: str) -> None:
        if self.timeline_aggregator is None:
            return
        await self.timeline_aggregator.invalidate(ticket_id)

    async def refresh_timeline(self, ticket: SupportTicket) -> TicketDetailResponse:
        await self._invalidate_timeline_cache(ticket.id)
        hydrated = await self.repository.get_ticket(ticket.id)
        if hydrated is None:
            hydrated = ticket
        serialized_ticket = _serialize_ticket(hydrated)
        messages = [
            ConversationResponse.model_validate(_conversation_to_dict(conversation))
            for conversation in hydrated.conversations
        ]
        external_entries: list[dict[str, Any]] = []
        if self.timeline_aggregator is not None:
            external_entries = await self.timeline_aggregator.collect(hydrated)
        timeline = _build_timeline(hydrated, external_entries=external_entries)
        attachments = _attachments_to_responses(getattr(hydrated, "attachments", []))
        return TicketDetailResponse.model_validate(
            {
                **serialized_ticket,
                "messages": messages,
                "timeline": timeline,
                "attachments": attachments,
            }
        )

    async def upload_attachment(self, ticket: SupportTicket, file: UploadFile) -> AttachmentResponse:
        if self.attachment_storage is None:
            raise RuntimeError("Attachment storage is not configured")
        relative_path, display_name = _build_attachment_destination(ticket.id, file.filename)
        content_type = file.content_type or "application/octet-stream"
        storage_result = await self.attachment_storage.save(file, relative_path)
        attachment = await self.repository.add_attachment(
            ticket,
            filename=display_name,
            content_type=content_type,
            size_bytes=storage_result.size_bytes,
            storage_path=storage_result.relative_path,
            uri=storage_result.uri,
        )
        await self._invalidate_timeline_cache(ticket.id)
        response = AttachmentResponse.model_validate(attachment)
        await self._publish_attachment_added(ticket, attachment)
        return response

    async def list_attachments(self, ticket: SupportTicket) -> list[AttachmentResponse]:
        attachments = await self.repository.list_attachments(ticket.id)
        return [AttachmentResponse.model_validate(item) for item in attachments]

    async def close_ticket(
        self,
        ticket: SupportTicket,
        payload: TicketCloseRequest | None,
    ) -> TicketDetailResponse:
        conversation: SupportConversation | None = None
        author_type = payload.author_type if payload and payload.author_type else "agent"
        if author_type not in _ALLOWED_AUTHOR_TYPES:
            author_type = "agent"
        if payload and payload.message:
            conversation = await self.repository.add_conversation(
                ticket,
                author_type=author_type,
                message=payload.message,
                attachment_uri=payload.attachment_uri,
                sentiment=payload.sentiment,
                metadata=payload.metadata,
                created_at=_now_utc(),
            )
            SUPPORT_CONVERSATION_ADDED_TOTAL.labels(
                author_type=normalise_author(author_type)
            ).inc()
        assigned_agent_id = (
            payload.assigned_agent_id if payload and payload.assigned_agent_id else ticket.assigned_agent_id
        )
        previous_status = ticket.status
        updated = await self.repository.update_status(
            ticket,
            status="closed",
            assigned_agent_id=assigned_agent_id,
        )
        SUPPORT_TICKET_STATUS_CHANGED_TOTAL.labels(
            status=normalise_status("closed")
        ).inc()
        await self._invalidate_timeline_cache(ticket.id)
        if conversation is not None:
            await self._publish_conversation_added(updated, conversation)
        await self._publish_status_changed(updated, previous_status)
        hydrated = await self.repository.get_ticket(ticket.id)
        if hydrated is None:
            hydrated = updated
        serialized_ticket = _serialize_ticket(hydrated)
        messages = [
            ConversationResponse.model_validate(_conversation_to_dict(conversation_entry))
            for conversation_entry in hydrated.conversations
        ]
        attachments = _attachments_to_responses(getattr(hydrated, "attachments", []))
        timeline = _build_timeline(hydrated)
        return TicketDetailResponse.model_validate(
            {
                **serialized_ticket,
                "messages": messages,
                "timeline": timeline,
                "attachments": attachments,
            }
        )

    async def _publish_case_opened(
        self,
        ticket: SupportTicket,
        initial_message: SupportConversation | None,
    ) -> None:
        if self.event_publisher is None:
            return
        await self.event_publisher.case_opened(ticket, initial_message)

    async def _publish_conversation_added(
        self,
        ticket: SupportTicket,
        conversation: SupportConversation,
    ) -> None:
        if self.event_publisher is None:
            return
        await self.event_publisher.conversation_added(ticket, conversation)

    async def _publish_status_changed(
        self,
        ticket: SupportTicket,
        previous_status: str,
    ) -> None:
        if self.event_publisher is None:
            return
        if previous_status == ticket.status:
            return
        await self.event_publisher.status_changed(ticket, previous_status)

    async def _publish_attachment_added(
        self,
        ticket: SupportTicket,
        attachment: SupportAttachment,
    ) -> None:
        if self.event_publisher is None:
            return
        await self.event_publisher.attachment_added(ticket, attachment)
