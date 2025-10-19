"""Background event handlers for support service integrations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from services.common import lifespan_session

from .events import SupportEventPublisher
from .repository import SupportRepository
from .schemas import ConversationCreate
from .services import SupportService
from .timeline import TimelineAggregatorProtocol


def _normalize_reference(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return str(value)


def _format_status(value: str | None) -> str:
    if not value:
        return "updated"
    cleaned = value.replace("_", " ").replace("-", " ").strip()
    return cleaned.capitalize() if cleaned else "updated"


def _sanitize_metadata(payload: dict[str, Any], *, order_ref: str | None, shipment_ref: str | None, tracking: str | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "eventType": payload.get("eventType"),
        "status": payload.get("status"),
        "orderId": order_ref,
        "shipmentId": shipment_ref,
        "trackingNumber": tracking,
        "occurredAt": payload.get("occurredAt") or payload.get("eventTime"),
        "carrier": payload.get("carrier") or payload.get("carrierCode"),
    }
    details = payload.get("details")
    if isinstance(details, dict):
        metadata["details"] = details
    context = payload.get("context")
    if isinstance(context, dict):
        metadata["context"] = context
    return {key: value for key, value in metadata.items() if value is not None}


class FulfillmentEventHandler:
    """Processes fulfillment events to keep ticket timelines enriched."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        aggregator: TimelineAggregatorProtocol | None,
        event_publisher: SupportEventPublisher | None,
    ) -> None:
        self._session_factory = session_factory
        self._aggregator = aggregator
        self.event_publisher = event_publisher

    async def handle(self, topic: str, payload: dict[str, Any]) -> None:
        if topic != "fulfillment.shipment.updated.v1":
            return
        await self._handle_shipment_update(payload)

    async def _handle_shipment_update(self, payload: dict[str, Any]) -> None:
        order_ref = _normalize_reference(payload.get("orderId") or payload.get("order_id"))
        if order_ref is None:
            order_ref = _normalize_reference(payload.get("order"))
        shipment_ref = _normalize_reference(payload.get("shipmentId") or payload.get("shipment_id"))
        tracking_number = _normalize_reference(payload.get("trackingNumber") or payload.get("tracking_number"))
        status_label = _format_status(_normalize_reference(payload.get("status")))
        message_subject = tracking_number or shipment_ref
        if message_subject is None and order_ref is None:
            # Nothing to map tickets with, ignore event.
            return

        async with lifespan_session(self._session_factory) as session:
            repository = SupportRepository(session)
            service = SupportService(repository, self._aggregator, None, self.event_publisher)

            tickets = await repository.find_tickets_by_references(
                order_reference=order_ref,
                shipment_reference=shipment_ref or tracking_number,
            )
            unique_tickets = {ticket.id: ticket for ticket in tickets}
            if tracking_number and tracking_number != (shipment_ref or tracking_number):
                extra = await repository.find_tickets_by_references(shipment_reference=tracking_number)
                for ticket in extra:
                    unique_tickets.setdefault(ticket.id, ticket)

            if not unique_tickets:
                return

            subject_text = message_subject or "update"
            message = f"Shipment {subject_text} updated to {status_label}"
            if order_ref:
                message = f"{message} for order {order_ref}"

            metadata = _sanitize_metadata(
                payload,
                order_ref=order_ref,
                shipment_ref=shipment_ref,
                tracking=tracking_number,
            )

            for ticket in unique_tickets.values():
                conversation_payload = ConversationCreate(
                    authorType="bot",
                    message=message,
                    metadata=metadata if metadata else None,
                )
                await service.add_message(ticket, conversation_payload)