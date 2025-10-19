"""Background event handlers for notification automation."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.ext.asyncio import async_sessionmaker

from services.common import lifespan_session

from .events import NotificationEventPublisher
from .metrics import (
    NOTIFICATION_EVENTS_DROPPED_TOTAL,
    NOTIFICATION_EVENTS_PROCESSED_TOTAL,
    NOTIFICATION_OPT_OUT_TOTAL,
    normalise_event_reason,
)
from .repository import NotificationRepository
from .schemas import NotificationCreate
from .services import NotificationProvider, NotificationService, RateLimitExceeded


def _parse_customer_id(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits:
            try:
                return int(digits)
            except ValueError:
                return None
    return None


def _clean(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value is not None}


def _title_case(value: str | None, fallback: str = "updated") -> str:
    if not value:
        return fallback
    cleaned = value.replace("_", " ").replace("-", " ").strip()
    return cleaned.capitalize() if cleaned else fallback


class NotificationEventHandler:
    """Consumes domain events and dispatches customer notifications."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        rate_limiter: Any,
        provider: NotificationProvider | None,
        event_publisher: NotificationEventPublisher | None,
    ) -> None:
        self._session_factory = session_factory
        self._rate_limiter = rate_limiter
        self._provider = provider
        self._event_publisher = event_publisher

    async def handle(self, topic: str, payload: dict[str, Any]) -> None:
        processed = False
        outcome = "unsupported_topic"
        if topic.startswith("support.case."):
            processed, outcome = await self._handle_support_event(topic, payload)
        elif topic == "order.status.changed.v1":
            processed, outcome = await self._handle_order_status(payload)
        elif topic == "fulfillment.shipment.updated.v1":
            processed, outcome = await self._handle_shipment_update(payload)

        reason = normalise_event_reason(outcome)
        if processed:
            NOTIFICATION_EVENTS_PROCESSED_TOTAL.labels(topic=topic).inc()
        else:
            NOTIFICATION_EVENTS_DROPPED_TOTAL.labels(topic=topic, reason=reason).inc()

    async def _handle_support_event(self, topic: str, payload: dict[str, Any]) -> tuple[bool, str]:
        ticket = payload.get("ticket")
        if not isinstance(ticket, dict):
            return False, "invalid_payload"

        customer_id = _parse_customer_id(ticket.get("customerId"))
        if customer_id is None:
            return False, "missing_customer"

        channel = (ticket.get("channel") or "email").strip().lower()
        recipient = self._resolve_recipient(
            channel,
            customer_id,
            email=ticket.get("customerEmail"),
            phone=ticket.get("customerPhone"),
        )
        if recipient is None:
            return False, "no_recipient"

        subject, body = self._support_message(topic, payload, ticket)
        metadata = self._support_metadata(topic, payload, ticket)

        outcome = await self._send_notification(
            customer_id=customer_id,
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            metadata=metadata,
        )
        return (outcome == "processed", outcome)

    async def _handle_order_status(self, payload: dict[str, Any]) -> tuple[bool, str]:
        order_obj = payload.get("order")
        if not isinstance(order_obj, dict):
            return False, "invalid_payload"
        order = cast(dict[str, Any], order_obj)

        customer_id = _parse_customer_id(order.get("customerId") or payload.get("customerId"))
        if customer_id is None:
            return False, "missing_customer"

        channel = (payload.get("channel") or order.get("channel") or "email").strip().lower()
        contact_obj = order.get("contact")
        contact: dict[str, Any] = contact_obj if isinstance(contact_obj, dict) else {}
        email = contact.get("email") or order.get("customerEmail") or payload.get("customerEmail")
        phone = contact.get("phone") or order.get("customerPhone") or payload.get("customerPhone")

        recipient = self._resolve_recipient(channel, customer_id, email=email, phone=phone)
        if recipient is None:
            return False, "no_recipient"

        subject, body = self._order_message(payload, order)
        metadata = self._order_metadata(payload, order)

        outcome = await self._send_notification(
            customer_id=customer_id,
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            metadata=metadata,
        )
        return (outcome == "processed", outcome)

    async def _handle_shipment_update(self, payload: dict[str, Any]) -> tuple[bool, str]:
        order_obj = payload.get("order")
        order_info: dict[str, Any] = order_obj if isinstance(order_obj, dict) else {}
        customer_id = _parse_customer_id(
            payload.get("customerId")
            or order_info.get("customerId")
        )
        if customer_id is None:
            return False, "missing_customer"

        channel = (payload.get("channel") or order_info.get("preferredChannel") or "email").strip().lower()
        contact_obj = payload.get("contact")
        contact: dict[str, Any] = contact_obj if isinstance(contact_obj, dict) else {}
        email = contact.get("email") or payload.get("customerEmail") or order_info.get("customerEmail")
        phone = contact.get("phone") or payload.get("customerPhone") or order_info.get("customerPhone")

        recipient = self._resolve_recipient(channel, customer_id, email=email, phone=phone)
        if recipient is None:
            return False, "no_recipient"

        subject, body = self._shipment_message(payload)
        metadata = self._shipment_metadata(payload)

        outcome = await self._send_notification(
            customer_id=customer_id,
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            metadata=metadata,
        )
        return (outcome == "processed", outcome)

    async def _send_notification(
        self,
        *,
        customer_id: int,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
        metadata: dict[str, Any] | None,
    ) -> str:
        async with lifespan_session(self._session_factory) as session:
            repository = NotificationRepository(session)
            if not await self._is_opted_in(repository, customer_id, channel):
                NOTIFICATION_OPT_OUT_TOTAL.labels(channel=channel).inc()
                return "opted_out"

            service = NotificationService(
                repository,
                provider=self._provider,
                rate_limiter=self._rate_limiter,
                event_publisher=self._event_publisher,
            )
            notification = await service.create_notification(
                NotificationCreate(
                    recipient=recipient,
                    channel=channel,
                    subject=subject,
                    body=body,
                    template=None,
                    metadata=metadata,
                )
            )
            try:
                await service.send_notification(notification)
            except RateLimitExceeded:
                await service.fail_notification(notification, reason="rate_limit_exceeded")
                return "rate_limited"
        return "processed"

    def _resolve_recipient(
        self,
        channel: str,
        customer_id: int,
        *,
        email: Any = None,
        phone: Any = None,
    ) -> str | None:
        if channel == "email":
            if isinstance(email, str) and email.strip():
                return email.strip()
            return f"customer-{customer_id}@example.com"
        if channel == "sms":
            if isinstance(phone, str) and phone.strip():
                return phone.strip()
            return None
        return None

    async def _is_opted_in(self, repository: NotificationRepository, customer_id: int, channel: str) -> bool:
        preferences = await repository.get_preferences(customer_id)
        for entry in preferences:
            if entry.channel.lower() == channel:
                return entry.opt_in
        return True

    def _support_message(
        self,
        topic: str,
        payload: dict[str, Any],
        ticket: dict[str, Any],
    ) -> tuple[str, str]:
        ticket_id = ticket.get("id") or "case"
        base_subject = ticket.get("subject") or "Support case update"
        change_type = payload.get("changeType")

        if topic == "support.case.closed.v1":
            subject = f"Support case {ticket_id} closed"
            body = f"Your support case '{base_subject}' has been closed."
            return subject, body

        subject = f"Update for support case {ticket_id}"
        if change_type == "conversation.added":
            conversation = payload.get("conversation") or {}
            author = (conversation.get("authorType") or "agent").strip() or "agent"
            message = conversation.get("message") or "A new message has been posted to your case."
            body = f"{author.capitalize()} wrote: {message}"
        elif change_type == "attachment.added":
            body = "A new attachment has been added to your support case."
        elif change_type == "status.changed":
            status = payload.get("currentStatus") or ticket.get("status")
            body = f"Your support case status is now {_title_case(status)}."
        else:
            body = f"There is a new update on your support case '{base_subject}'."
        return subject, body

    def _support_metadata(
        self,
        topic: str,
        payload: dict[str, Any],
        ticket: dict[str, Any],
    ) -> dict[str, Any] | None:
        conversation = payload.get("conversation") or {}
        attachment = payload.get("attachment") or {}
        metadata = {
            "topic": topic,
            "ticketId": ticket.get("id"),
            "changeType": payload.get("changeType"),
            "conversationId": conversation.get("id"),
            "attachmentId": attachment.get("id"),
            "occurredAt": payload.get("occurredAt"),
        }
        return _clean(metadata) or None

    def _order_message(
        self,
        payload: dict[str, Any],
        order: dict[str, Any],
    ) -> tuple[str, str]:
        order_id = order.get("id") or order.get("orderId") or order.get("number")
        current_status = payload.get("currentStatus") or order.get("status")
        previous_status = payload.get("previousStatus")

        status_label = _title_case(current_status)
        previous_label = _title_case(previous_status) if previous_status else None

        if order_id is None:
            subject = "Order status updated"
            order_ref = "your order"
        else:
            subject = f"Order {order_id} status updated"
            order_ref = f"order {order_id}"

        if current_status:
            subject = f"Order {order_id} status updated to {status_label}" if order_id else f"Your order is now {status_label}"

        body = f"Your {order_ref} is now {status_label}."
        if previous_label:
            body += f" Previously it was {previous_label}."
        return subject, body

    def _order_metadata(
        self,
        payload: dict[str, Any],
        order: dict[str, Any],
    ) -> dict[str, Any] | None:
        metadata = {
            "topic": "order.status.changed.v1",
            "orderId": order.get("id") or order.get("orderId") or order.get("number"),
            "previousStatus": payload.get("previousStatus"),
            "currentStatus": payload.get("currentStatus") or order.get("status"),
            "occurredAt": payload.get("occurredAt"),
        }
        return _clean(metadata) or None

    def _shipment_message(self, payload: dict[str, Any]) -> tuple[str, str]:
        tracking = payload.get("trackingNumber")
        status = payload.get("status")
        order_id = payload.get("orderId")

        status_label = _title_case(status)
        if tracking:
            subject = f"Shipment update for {tracking}"
            body = f"Your shipment {tracking} is now {status_label}."
        else:
            subject = "Shipment status updated"
            body = f"Your shipment is now {status_label}."
        if order_id is not None:
            body += f" (Order {order_id})."
        return subject, body

    def _shipment_metadata(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        metadata = {
            "topic": "fulfillment.shipment.updated.v1",
            "orderId": payload.get("orderId"),
            "shipmentId": payload.get("shipmentId"),
            "trackingNumber": payload.get("trackingNumber"),
            "status": payload.get("status"),
            "carrier": payload.get("carrier"),
            "occurredAt": payload.get("occurredAt"),
        }
        return _clean(metadata) or None
