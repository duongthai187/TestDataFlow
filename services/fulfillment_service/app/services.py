"""Domain services for fulfillment operations."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from .models import ReturnRequest, Shipment
from .repository import FulfillmentRepository
from .schemas import (
    ReturnCreate,
    ShipmentCreate,
    ShipmentStatusUpdate,
    ShipmentTaskCreate,
)


_ALLOWED_STATUSES = {
    "pending",
    "ready",
    "processing",
    "packed",
    "shipped",
    "delivered",
    "cancelled",
    "delayed",
    "return_initiated",
}

_STATUS_TRANSITIONS = {
    "pending": {"ready", "processing", "packed", "cancelled"},
    "ready": {"processing", "packed", "shipped", "cancelled"},
    "processing": {"packed", "shipped", "cancelled"},
    "packed": {"shipped", "cancelled", "delayed"},
    "shipped": {"delivered", "delayed", "return_initiated"},
    "delivered": {"return_initiated"},
    "delayed": {"shipped", "delivered", "cancelled"},
    "return_initiated": set(),
    "cancelled": set(),
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _generate_tracking_number(order_id: int) -> str:
    suffix = secrets.token_hex(4).upper()
    return f"TRK-{order_id}-{suffix}"


def _generate_rma_code() -> str:
    return secrets.token_hex(4).upper()


def _convert_task(task: ShipmentTaskCreate) -> dict[str, object]:
    status = task.status or "pending"
    return {
        "task_type": task.task_type,
        "status": status if status in _ALLOWED_STATUSES else "pending",
        "assigned_to": task.assigned_to,
        "deadline": task.deadline,
        "payload": task.payload,
    }


class FulfillmentService:
    """Application service orchestrating fulfillment logic."""

    def __init__(self, repository: FulfillmentRepository) -> None:
        self.repository = repository

    async def create_shipment(self, payload: ShipmentCreate) -> Shipment:
        tracking_number = payload.tracking_number or _generate_tracking_number(payload.order_id)
        tasks = [_convert_task(task) for task in payload.tasks]
        shipment = await self.repository.create_shipment(
            order_id=payload.order_id,
            fulfillment_center_id=payload.fulfillment_center_id,
            carrier_code=payload.carrier,
            service_level=payload.service_level,
            status="pending",
            tracking_number=tracking_number,
            estimated_delivery=payload.estimated_delivery,
            tasks=tasks,
        )
        await self.repository.add_event(
            shipment,
            event_type="created",
            payload={
                "status": shipment.status,
                "trackingNumber": shipment.tracking_number,
            },
        )
        return shipment

    async def update_status(self, shipment: Shipment, payload: ShipmentStatusUpdate) -> Shipment:
        target_status = payload.status.lower()
        if target_status not in _ALLOWED_STATUSES:
            raise ValueError("Unsupported status transition")

        current = shipment.status.lower()
        if current == target_status:
            raise ValueError("Shipment already in target status")

        allowed = _STATUS_TRANSITIONS.get(current, set())
        if allowed and target_status not in allowed:
            raise ValueError("Invalid status transition")

        shipped_at = shipment.shipped_at
        delivered_at = shipment.delivered_at
        if target_status == "shipped" and shipped_at is None:
            shipped_at = _now_utc()
        if target_status == "delivered":
            if shipped_at is None:
                shipped_at = _now_utc()
            delivered_at = _now_utc()

        updated = await self.repository.update_shipment(
            shipment,
            status=target_status,
            tracking_number=payload.tracking_number or shipment.tracking_number,
            shipped_at=shipped_at,
            delivered_at=delivered_at,
            estimated_delivery=payload.estimated_delivery or shipment.estimated_delivery,
        )
        await self.repository.add_event(
            updated,
            event_type=f"status.{target_status}",
            payload={
                "status": target_status,
                "description": payload.description,
                "trackingNumber": updated.tracking_number,
            },
        )
        return updated

    async def create_return(self, payload: ReturnCreate) -> ReturnRequest:
        shipment = None
        if payload.shipment_id is not None:
            shipment = await self.repository.get_shipment(payload.shipment_id)
            if shipment is None:
                raise ValueError("Shipment not found for return")
        authorization_code = _generate_rma_code()
        return_request = await self.repository.create_return_request(
            order_id=payload.order_id,
            shipment=shipment,
            authorization_code=authorization_code,
            reason=payload.reason,
        )
        if shipment is not None:
            await self.repository.add_event(
                shipment,
                event_type="return.created",
                payload={"returnId": return_request.id, "authorizationCode": authorization_code},
            )
        return return_request

    async def track_shipment(self, tracking_number: str) -> Shipment:
        shipment = await self.repository.get_shipment_by_tracking(tracking_number)
        if shipment is None:
            raise ValueError("Shipment not found")
        return shipment