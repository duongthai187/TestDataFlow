"""Database helpers for the fulfillment service."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import ReturnRequest, Shipment, ShipmentEvent, ShipmentTask


class FulfillmentRepository:
    """Persistence helpers for shipments, tasks, and returns."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_shipment(
        self,
        *,
        order_id: int,
        fulfillment_center_id: int,
        carrier_code: str,
        service_level: str,
        status: str,
        tracking_number: str | None,
        estimated_delivery: datetime | None,
        tasks: list[dict[str, object]],
    ) -> Shipment:
        shipment = Shipment(
            order_id=order_id,
            fulfillment_center_id=fulfillment_center_id,
            carrier_code=carrier_code,
            service_level=service_level,
            status=status,
            tracking_number=tracking_number,
            estimated_delivery=estimated_delivery,
        )
        self.session.add(shipment)
        await self.session.flush()

        for task in tasks:
            self.session.add(
                ShipmentTask(
                    shipment_id=shipment.id,
                    task_type=task["task_type"],
                    status=task["status"],
                    assigned_to=task.get("assigned_to"),
                    deadline=task.get("deadline"),
                    payload_json=json.dumps(task.get("payload") or {}),
                )
            )

        await self.session.flush()
        await self.session.refresh(shipment, attribute_names=["created_at", "updated_at"])
        await self.session.refresh(shipment, attribute_names=["tasks"])
        return shipment

    async def add_event(
        self,
        shipment: Shipment,
        *,
        event_type: str,
        payload: dict[str, object],
    ) -> ShipmentEvent:
        event = ShipmentEvent(
            shipment=shipment,
            type=event_type,
            payload=json.dumps(payload, default=str),
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def list_shipments(
        self,
        *,
        order_id: int | None,
        status: str | None,
        tracking_number: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Shipment], int]:
        filters = []
        if order_id is not None:
            filters.append(Shipment.order_id == order_id)
        if status is not None:
            filters.append(Shipment.status == status)
        if tracking_number is not None:
            filters.append(Shipment.tracking_number == tracking_number)

        base: Select[tuple[Shipment]] = (
            select(Shipment)
            .options(selectinload(Shipment.tasks), selectinload(Shipment.events))
            .order_by(Shipment.created_at.desc(), Shipment.id.desc())
        )
        count: Select[tuple[int]] = select(func.count(Shipment.id))

        if filters:
            clause = and_(*filters)
            base = base.where(clause)
            count = count.where(clause)

        total = (await self.session.execute(count)).scalar_one()
        result = await self.session.execute(base.offset(offset).limit(limit))
        shipments = list(result.scalars().unique())
        return shipments, total

    async def get_shipment(self, shipment_id: int) -> Shipment | None:
        result = await self.session.execute(
            select(Shipment)
            .options(selectinload(Shipment.tasks), selectinload(Shipment.events), selectinload(Shipment.returns))
            .where(Shipment.id == shipment_id)
        )
        return result.scalar_one_or_none()

    async def get_shipment_by_tracking(self, tracking_number: str) -> Shipment | None:
        result = await self.session.execute(
            select(Shipment)
            .options(selectinload(Shipment.tasks), selectinload(Shipment.events))
            .where(Shipment.tracking_number == tracking_number)
        )
        return result.scalar_one_or_none()

    async def update_shipment(
        self,
        shipment: Shipment,
        *,
        status: str,
        tracking_number: str | None,
        shipped_at: datetime | None,
        delivered_at: datetime | None,
        estimated_delivery: datetime | None,
    ) -> Shipment:
        shipment.status = status
        shipment.tracking_number = tracking_number
        shipment.shipped_at = shipped_at
        shipment.delivered_at = delivered_at
        shipment.estimated_delivery = estimated_delivery
        await self.session.flush()
        await self.session.refresh(
            shipment,
            attribute_names=["updated_at", "status", "tracking_number", "shipped_at", "delivered_at", "estimated_delivery"],
        )
        return shipment

    async def delete_shipment(self, shipment: Shipment) -> None:
        await self.session.delete(shipment)
        await self.session.flush()

    async def create_return_request(
        self,
        *,
        order_id: int,
        shipment: Shipment | None,
        authorization_code: str,
        reason: str | None,
    ) -> ReturnRequest:
        return_request = ReturnRequest(
            order_id=order_id,
            shipment=shipment,
            authorization_code=authorization_code,
            reason=reason,
        )
        self.session.add(return_request)
        await self.session.flush()
        await self.session.refresh(return_request)
        return return_request

    async def get_return(self, return_id: int) -> ReturnRequest | None:
        result = await self.session.execute(
            select(ReturnRequest).options(selectinload(ReturnRequest.shipment)).where(ReturnRequest.id == return_id)
        )
        return result.scalar_one_or_none()