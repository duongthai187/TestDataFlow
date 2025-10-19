"""Inventory domain services."""

from __future__ import annotations

from dataclasses import dataclass

from .models import InventoryItem
from .repository import InventoryRepository
from .schemas import InventoryCreate


@dataclass
class ReservationResult:
    available: int
    reserved: int


class InventoryService:
    """High-level inventory orchestration."""

    def __init__(self, repository: InventoryRepository) -> None:
        self.repository = repository

    async def create_item(self, payload: InventoryCreate) -> InventoryItem:
        item = await self.repository.create_item(
            sku=payload.sku,
            location=payload.location,
            quantity_on_hand=payload.quantity_on_hand,
            safety_stock=payload.safety_stock,
        )
        await self.repository.add_event(item, event_type="created", payload=str(payload.quantity_on_hand))
        return item

    async def adjust_stock(
        self,
        item: InventoryItem,
        *,
        quantity_on_hand: int,
        safety_stock: int | None,
    ) -> InventoryItem:
        previous_safety = item.safety_stock

        if quantity_on_hand < item.quantity_reserved:
            msg = "quantity on hand cannot be less than reserved"
            raise ValueError(msg)
        new_safety = safety_stock if safety_stock is not None else item.safety_stock
        updated = await self.repository.update_quantities(
            item,
            quantity_on_hand=quantity_on_hand,
            quantity_reserved=item.quantity_reserved,
        )
        updated.safety_stock = new_safety
        await self.repository.session.flush()
        await self.repository.session.refresh(updated, attribute_names=["updated_at"])
        await self.repository.add_event(
            updated,
            event_type="adjusted",
            payload=str(quantity_on_hand),
        )
        if safety_stock is not None and new_safety != previous_safety:
            await self.repository.add_event(updated, event_type="safety_stock_updated", payload=str(new_safety))
        return updated

    async def increment_stock(self, item: InventoryItem, *, quantity: int) -> InventoryItem:
        if quantity < 0:
            msg = "increment quantity must be non-negative"
            raise ValueError(msg)
        updated = await self.repository.update_quantities(
            item,
            quantity_on_hand=item.quantity_on_hand + quantity,
            quantity_reserved=item.quantity_reserved,
        )
        await self.repository.add_event(updated, event_type="stock_received", payload=str(quantity))
        return updated

    async def reserve(self, item: InventoryItem, *, quantity: int) -> InventoryItem:
        if quantity <= 0:
            msg = "quantity must be positive"
            raise ValueError(msg)
        available = item.quantity_on_hand - item.quantity_reserved
        if quantity > available:
            msg = "insufficient available quantity"
            raise ValueError(msg)
        updated = await self.repository.update_quantities(
            item,
            quantity_on_hand=item.quantity_on_hand,
            quantity_reserved=item.quantity_reserved + quantity,
        )
        await self.repository.add_event(updated, event_type="reserved", payload=str(quantity))
        return updated

    async def release(self, item: InventoryItem, *, quantity: int) -> InventoryItem:
        if quantity <= 0:
            msg = "quantity must be positive"
            raise ValueError(msg)
        if quantity > item.quantity_reserved:
            msg = "cannot release more than reserved"
            raise ValueError(msg)
        updated = await self.repository.update_quantities(
            item,
            quantity_on_hand=item.quantity_on_hand,
            quantity_reserved=item.quantity_reserved - quantity,
        )
        await self.repository.add_event(updated, event_type="released", payload=str(quantity))
        return updated

    async def commit(self, item: InventoryItem, *, quantity: int) -> InventoryItem:
        if quantity <= 0:
            msg = "quantity must be positive"
            raise ValueError(msg)
        if quantity > item.quantity_reserved:
            msg = "cannot commit more than reserved"
            raise ValueError(msg)
        if quantity > item.quantity_on_hand:
            msg = "cannot commit more than on-hand"
            raise ValueError(msg)
        updated = await self.repository.update_quantities(
            item,
            quantity_on_hand=item.quantity_on_hand - quantity,
            quantity_reserved=item.quantity_reserved - quantity,
        )
        await self.repository.add_event(updated, event_type="committed", payload=str(quantity))
        return updated
