"""Database helpers for the payment service."""

from __future__ import annotations

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Payment, PaymentEvent


class PaymentRepository:
    """Persistence utilities for payments."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_payment(
        self,
        *,
        order_id: int | None,
        customer_id: int,
        amount_cents: int,
        currency: str,
        payment_method: str,
        provider_reference: str | None,
    ) -> Payment:
        payment = Payment(
            order_id=order_id,
            customer_id=customer_id,
            amount_cents=amount_cents,
            currency=currency,
            payment_method=payment_method,
            provider_reference=provider_reference,
        )
        self.session.add(payment)
        await self.session.flush()
        await self.session.refresh(payment, attribute_names=["created_at", "updated_at"])
        return payment

    async def get_payment(self, payment_id: int) -> Payment | None:
        result = await self.session.execute(
            select(Payment)
            .options(selectinload(Payment.events))
            .where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()

    async def list_payments(
        self,
        *,
        customer_id: int | None,
        order_id: int | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Payment], int]:
        filters = []
        if customer_id is not None:
            filters.append(Payment.customer_id == customer_id)
        if order_id is not None:
            filters.append(Payment.order_id == order_id)
        if status is not None:
            filters.append(Payment.status == status)

        base: Select[tuple[Payment]] = select(Payment).order_by(Payment.created_at.desc(), Payment.id.desc())
        count: Select[tuple[int]] = select(func.count(Payment.id))

        if filters:
            combined = and_(*filters)
            base = base.where(combined)
            count = count.where(combined)

        total = (await self.session.execute(count)).scalar_one()
        result = await self.session.execute(
            base.options(selectinload(Payment.events)).offset(offset).limit(limit)
        )
        payments = list(result.scalars().unique())
        return payments, total

    async def update_status(self, payment: Payment, *, status: str) -> Payment:
        payment.status = status
        await self.session.flush()
        await self.session.refresh(payment, attribute_names=["updated_at"])
        return payment

    async def update_provider_reference(self, payment: Payment, *, reference: str | None) -> Payment:
        payment.provider_reference = reference
        await self.session.flush()
        await self.session.refresh(payment, attribute_names=["updated_at"])
        return payment

    async def add_event(self, payment: Payment, *, event_type: str, payload: str) -> PaymentEvent:
        event = PaymentEvent(payment=payment, type=event_type, payload=payload)
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def delete_payment(self, payment: Payment) -> None:
        await self.session.delete(payment)
        await self.session.flush()
