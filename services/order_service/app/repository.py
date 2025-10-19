"""Data access helpers for order service."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Order, OrderEvent, OrderItem


class OrderRepository:
    """Persistence helpers for orders and related entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_order(
        self,
        *,
        customer_id: int,
        currency: str,
        items: list[dict[str, int]],
        shipping_cents: int,
        tax_cents: int,
        discount_cents: int,
    ) -> Order:
        order = Order(
            customer_id=customer_id,
            currency=currency,
            shipping_total_cents=shipping_cents,
            tax_total_cents=tax_cents,
            discount_total_cents=discount_cents,
        )
        self.session.add(order)
        await self.session.flush()

        subtotal = 0
        for entry in items:
            item = OrderItem(
                order=order,
                sku=entry["sku"],
                name=entry["name"],
                quantity=entry["quantity"],
                unit_price_cents=entry["unit_price_cents"],
                discount_amount_cents=entry.get("discount_amount_cents", 0),
                tax_amount_cents=entry.get("tax_amount_cents", 0),
            )
            subtotal += item.unit_price_cents * item.quantity - item.discount_amount_cents
            self.session.add(item)

        order.subtotal_cents = subtotal
        order.grand_total_cents = subtotal - discount_cents + shipping_cents + tax_cents
        await self.session.flush()
        await self.session.refresh(order, attribute_names=["items", "created_at", "updated_at"])
        return order

    async def get_order(self, order_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.events))
            .where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def list_orders(
        self,
        *,
        customer_id: int | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Order], int]:
        base: Select[tuple[Order]] = select(Order)
        count: Select[tuple[int]] = select(func.count(func.distinct(Order.id)))

        filters = []
        if customer_id is not None:
            filters.append(Order.customer_id == customer_id)
        if status is not None:
            filters.append(Order.status == status)

        if filters:
            base = base.where(and_(*filters))
            count = count.where(and_(*filters))

        base = base.order_by(Order.created_at.desc(), Order.id.desc())

        total_result = await self.session.execute(count)
        total = total_result.scalar_one()

        result = await self.session.execute(
            base.options(selectinload(Order.items)).offset(offset).limit(limit)
        )
        orders = list(result.scalars().unique())
        return orders, total

    async def add_event(
        self,
        order: Order,
        *,
        event_type: str,
        payload: str,
    ) -> OrderEvent:
        entry = OrderEvent(order=order, type=event_type, payload=payload)
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    async def update_status(self, order: Order, *, status: str) -> Order:
        order.status = status
        await self.session.flush()
        await self.session.refresh(order, attribute_names=["updated_at"])
        return order

    async def mark_paid(self, order: Order) -> Order:
        order.is_paid = True
        await self.session.flush()
        await self.session.refresh(order, attribute_names=["updated_at"])
        return order

    async def delete_order(self, order: Order) -> None:
        await self.session.delete(order)
        await self.session.flush()
