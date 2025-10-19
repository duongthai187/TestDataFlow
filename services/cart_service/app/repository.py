"""Data access helpers for the cart service."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Cart, CartItem


class CartRepository:
    """Persistence helpers for shopping carts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_cart(self, *, customer_id: int, currency: str) -> Cart:
        result = await self.session.execute(
            select(Cart).options(selectinload(Cart.items)).where(Cart.customer_id == customer_id)
        )
        cart = result.scalar_one_or_none()
        if cart is None:
            cart = Cart(customer_id=customer_id, currency=currency)
            self.session.add(cart)
            await self.session.flush()
            await self.session.refresh(cart, attribute_names=["created_at", "updated_at", "items"])
        return cart

    async def get_cart(self, *, customer_id: int) -> Cart | None:
        result = await self.session.execute(
            select(Cart).options(selectinload(Cart.items)).where(Cart.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def add_item(
        self,
        cart: Cart,
        *,
        sku: str,
        name: str,
        unit_price_cents: int,
        quantity: int,
    ) -> Cart:
        existing = next((item for item in cart.items if item.sku == sku), None)
        if existing:
            existing.quantity += quantity
            existing.unit_price_cents = unit_price_cents
        else:
            cart.items.append(
                CartItem(
                    sku=sku,
                    name=name,
                    unit_price_cents=unit_price_cents,
                    quantity=quantity,
                )
            )
        await self.session.flush()
        await self.session.refresh(cart, attribute_names=["items", "updated_at"])
        return cart

    async def update_item(
        self,
        cart: Cart,
        *,
        sku: str,
        unit_price_cents: int | None,
        quantity: int | None,
    ) -> Cart:
        item = next((entry for entry in cart.items if entry.sku == sku), None)
        if item is None:
            raise KeyError("Item not found")
        if quantity is not None:
            item.quantity = quantity
        if unit_price_cents is not None:
            item.unit_price_cents = unit_price_cents
        await self.session.flush()
        await self.session.refresh(cart, attribute_names=["items", "updated_at"])
        return cart

    async def remove_item(self, cart: Cart, *, sku: str) -> Cart:
        item = next((entry for entry in cart.items if entry.sku == sku), None)
        if item is None:
            raise KeyError("Item not found")
        await self.session.delete(item)
        await self.session.flush()
        await self.session.refresh(cart, attribute_names=["items", "updated_at"])
        return cart

    async def clear_cart(self, cart: Cart) -> None:
        for item in list(cart.items):
            await self.session.delete(item)
        await self.session.flush()
        await self.session.refresh(cart, attribute_names=["items", "updated_at"])

    async def delete_cart(self, cart: Cart) -> None:
        await self.session.delete(cart)
        await self.session.flush()

    async def cart_totals(self, cart: Cart) -> tuple[int, Decimal]:
        total_items = sum(item.quantity for item in cart.items)
        total_amount = Decimal(sum(item.unit_price_cents * item.quantity for item in cart.items)) / Decimal("100")
        return total_items, total_amount

    async def count_items(self, *, customer_id: int) -> int:
        query: Select[tuple[int]] = select(func.sum(CartItem.quantity)).join(Cart)
        result = await self.session.execute(query.where(Cart.customer_id == customer_id))
        total = result.scalar_one_or_none()
        return int(total or 0)
