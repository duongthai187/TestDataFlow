"""Data access helpers for inventory service."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import InventoryEvent, InventoryItem


class InventoryRepository:
    """Persistence utilities for inventory items and events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_item(
        self,
        *,
        sku: str,
        location: str | None,
        quantity_on_hand: int,
        safety_stock: int,
    ) -> InventoryItem:
        item = InventoryItem(
            sku=sku,
            location=location,
            quantity_on_hand=quantity_on_hand,
            safety_stock=safety_stock,
        )
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item, attribute_names=["created_at", "updated_at"])
        return item

    async def get_item(self, item_id: int) -> InventoryItem | None:
        result = await self.session.execute(
            select(InventoryItem)
            .options(selectinload(InventoryItem.events))
            .where(InventoryItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def find_by_sku(self, sku: str, location: str | None) -> InventoryItem | None:
        stmt = select(InventoryItem).where(InventoryItem.sku == sku)
        if location is None:
            stmt = stmt.where(InventoryItem.location.is_(None))
        else:
            stmt = stmt.where(InventoryItem.location == location)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_items(
        self,
        *,
        sku: str | None,
        location: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[InventoryItem], int]:
        filters = []
        if sku is not None:
            filters.append(InventoryItem.sku == sku)
        if location is not None:
            filters.append(InventoryItem.location == location)

        base: Select[tuple[InventoryItem]] = select(InventoryItem).order_by(
            InventoryItem.created_at.desc(), InventoryItem.id.desc()
        )
        count: Select[tuple[int]] = select(func.count(InventoryItem.id))

        if filters:
            clause = and_(*filters)
            base = base.where(clause)
            count = count.where(clause)

        total = (await self.session.execute(count)).scalar_one()
        result = await self.session.execute(
            base.offset(offset).limit(limit).options(selectinload(InventoryItem.events))
        )
        items = list(result.scalars().unique())
        return items, total

    async def add_event(self, item: InventoryItem, *, event_type: str, payload: str) -> InventoryEvent:
        event = InventoryEvent(item=item, type=event_type, payload=payload)
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def update_quantities(
        self,
        item: InventoryItem,
        *,
        quantity_on_hand: int,
        quantity_reserved: int,
    ) -> InventoryItem:
        item.quantity_on_hand = quantity_on_hand
        item.quantity_reserved = quantity_reserved
        await self.session.flush()
        await self.session.refresh(item, attribute_names=["updated_at"])
        return item

    async def delete_item(self, item: InventoryItem) -> None:
        await self.session.delete(item)
        await self.session.flush()
