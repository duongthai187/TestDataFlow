"""Service layer for orchestrating order operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Protocol

from .models import Order
from .repository import OrderRepository
from .schemas import OrderCreate


class PricingProvider(Protocol):
    async def resolve_price(self, *, sku: str, quantity: int) -> tuple[Decimal, str]: ...


class InventoryProvider(Protocol):
    async def reserve(self, *, sku: str, quantity: int) -> None: ...


class NotificationProvider(Protocol):
    async def send_order_confirmation(self, order: Order) -> None: ...


@dataclass
class OrderTotals:
    currency: str
    subtotal: Decimal
    discount_total: Decimal
    shipping_total: Decimal
    tax_total: Decimal
    grand_total: Decimal


def _to_cents(amount: Decimal) -> int:
    return int((amount * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


class OrderService:
    """High-level operations on orders."""

    def __init__(
        self,
        repository: OrderRepository,
        pricing: PricingProvider | None = None,
        inventory: InventoryProvider | None = None,
        notifications: NotificationProvider | None = None,
    ) -> None:
        self.repository = repository
        self.pricing = pricing
        self.inventory = inventory
        self.notifications = notifications

    async def create_order(self, payload: OrderCreate) -> Order:
        items_payload = []
        subtotal = Decimal("0")
        currency = payload.currency

        for item in payload.items:
            price = item.unit_price
            if self.pricing:
                price, provider_currency = await self.pricing.resolve_price(sku=item.sku, quantity=item.quantity)
                if provider_currency != payload.currency:
                    msg = "Currency mismatch between pricing provider and order"
                    raise ValueError(msg)
            subtotal += (price - item.discount_amount) * item.quantity
            items_payload.append(
                {
                    "sku": item.sku,
                    "name": item.name,
                    "quantity": item.quantity,
                    "unit_price_cents": _to_cents(price),
                    "discount_amount_cents": _to_cents(item.discount_amount),
                    "tax_amount_cents": _to_cents(item.tax_amount),
                }
            )

        shipping_cents = _to_cents(payload.shipping_total)
        tax_cents = _to_cents(payload.tax_total)
        discount_cents = _to_cents(payload.discount_total)

        order = await self.repository.create_order(
            customer_id=payload.customer_id,
            currency=currency,
            items=items_payload,
            shipping_cents=shipping_cents,
            tax_cents=tax_cents,
            discount_cents=discount_cents,
        )

        order.subtotal_cents = _to_cents(subtotal)
        order.grand_total_cents = _to_cents(
            subtotal - payload.discount_total + payload.shipping_total + payload.tax_total
        )
        await self.repository.session.flush()
        await self.repository.session.refresh(order, attribute_names=["items", "updated_at"])

        if self.inventory:
            for item in order.items:
                await self.inventory.reserve(sku=item.sku, quantity=item.quantity)

        if self.notifications:
            await self.notifications.send_order_confirmation(order)

        return order

    async def update_status(self, order: Order, *, status: str) -> Order:
        await self.repository.add_event(order, event_type="status_changed", payload=status)
        return await self.repository.update_status(order, status=status)

    async def mark_paid(self, order: Order) -> Order:
        await self.repository.add_event(order, event_type="payment_captured", payload="paid")
        return await self.repository.mark_paid(order)
