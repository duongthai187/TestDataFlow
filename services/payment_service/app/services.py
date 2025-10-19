"""Service layer for payment operations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

from .models import Payment
from .repository import PaymentRepository
from .schemas import PaymentCreate


class PaymentGateway(Protocol):
    async def authorize(self, *, amount: Decimal, currency: str, payment_method: str, metadata: dict | None) -> str: ...

    async def capture(self, *, provider_reference: str) -> None: ...

    async def refund(self, *, provider_reference: str, amount: Decimal | None = None) -> None: ...


def _to_cents(amount: Decimal) -> int:
    return int((amount * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


@dataclass
class PaymentStatusChange:
    status: str
    message: str


class PaymentService:
    """High level payment orchestration."""

    def __init__(self, repository: PaymentRepository, gateway: PaymentGateway | None = None) -> None:
        self.repository = repository
        self.gateway = gateway

    async def create_payment(self, payload: PaymentCreate) -> Payment:
        provider_reference = payload.provider_reference

        if self.gateway and provider_reference is None:
            reference = await self.gateway.authorize(
                amount=payload.amount,
                currency=payload.currency,
                payment_method=payload.payment_method,
                metadata=payload.metadata,
            )
            provider_reference = reference

        payment = await self.repository.create_payment(
            order_id=payload.order_id,
            customer_id=payload.customer_id,
            amount_cents=_to_cents(payload.amount),
            currency=payload.currency,
            payment_method=payload.payment_method,
            provider_reference=provider_reference,
        )
        await self.repository.add_event(payment, event_type="created", payload=payment.status)
        if provider_reference:
            await self.repository.add_event(payment, event_type="provider_linked", payload=provider_reference)
        return payment

    async def update_status(self, payment: Payment, *, status: str) -> Payment:
        await self.repository.add_event(payment, event_type="status_changed", payload=status)
        return await self.repository.update_status(payment, status=status)

    async def capture(self, payment: Payment) -> Payment:
        if self.gateway and payment.provider_reference:
            await self.gateway.capture(provider_reference=payment.provider_reference)
        await self.repository.add_event(payment, event_type="payment_captured", payload="captured")
        return await self.update_status(payment, status="captured")

    async def refund(self, payment: Payment, *, amount: Decimal | None = None) -> Payment:
        if self.gateway and payment.provider_reference:
            await self.gateway.refund(provider_reference=payment.provider_reference, amount=amount)
        payload = str(amount) if amount is not None else "full"
        await self.repository.add_event(payment, event_type="payment_refunded", payload=payload)
        return await self.update_status(payment, status="refunded")

    async def update_provider_reference(self, payment: Payment, *, reference: str | None) -> Payment:
        await self.repository.add_event(payment, event_type="provider_reference_updated", payload=reference or "")
        return await self.repository.update_provider_reference(payment, reference=reference)
