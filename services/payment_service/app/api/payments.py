"""HTTP endpoints for payment management."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..dependencies import get_repository
from ..repository import PaymentRepository
from ..schemas import (
    PaymentCreate,
    PaymentEventResponse,
    PaymentListResponse,
    PaymentProviderUpdate,
    PaymentRefundRequest,
    PaymentResponse,
    PaymentUpdateStatus,
)
from ..services import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


def _format_amount(value: int) -> Decimal:
    return (Decimal(value) / Decimal("100")).quantize(Decimal("0.01"))


def _serialize_payment(payment) -> dict[str, object]:
    return {
        "id": payment.id,
        "customerId": payment.customer_id,
        "orderId": payment.order_id,
        "amount": _format_amount(payment.amount_cents),
        "currency": payment.currency,
        "status": payment.status,
        "paymentMethod": payment.payment_method,
        "providerReference": payment.provider_reference,
        "createdAt": payment.created_at,
        "updatedAt": payment.updated_at,
    }


def _serialize_events(payment) -> list[dict[str, object]]:
    return [
        {
            "type": event.type,
            "payload": event.payload,
            "createdAt": event.created_at,
        }
        for event in payment.events
    ]


@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: PaymentCreate,
    repository: PaymentRepository = Depends(get_repository),
) -> PaymentResponse:
    service = PaymentService(repository)
    payment = await service.create_payment(payload)
    return PaymentResponse.model_validate(_serialize_payment(payment))


@router.get("", response_model=PaymentListResponse)
async def list_payments(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    customer_id: int | None = Query(default=None, alias="customerId"),
    order_id: int | None = Query(default=None, alias="orderId"),
    status_filter: str | None = Query(default=None, alias="status"),
    repository: PaymentRepository = Depends(get_repository),
) -> PaymentListResponse:
    payments, total = await repository.list_payments(
        customer_id=customer_id,
        order_id=order_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    items = [PaymentResponse.model_validate(_serialize_payment(payment)) for payment in payments]
    return PaymentListResponse(items=items, total=total)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(payment_id: int, repository: PaymentRepository = Depends(get_repository)) -> PaymentResponse:
    payment = await repository.get_payment(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return PaymentResponse.model_validate(_serialize_payment(payment))


@router.patch("/{payment_id}/status", response_model=PaymentResponse)
async def update_payment_status(
    payment_id: int,
    payload: PaymentUpdateStatus,
    repository: PaymentRepository = Depends(get_repository),
) -> PaymentResponse:
    payment = await repository.get_payment(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    service = PaymentService(repository)
    updated = await service.update_status(payment, status=payload.status)
    return PaymentResponse.model_validate(_serialize_payment(updated))


@router.post("/{payment_id}/capture", response_model=PaymentResponse)
async def capture_payment(payment_id: int, repository: PaymentRepository = Depends(get_repository)) -> PaymentResponse:
    payment = await repository.get_payment(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    service = PaymentService(repository)
    captured = await service.capture(payment)
    return PaymentResponse.model_validate(_serialize_payment(captured))


@router.post("/{payment_id}/refund", response_model=PaymentResponse)
async def refund_payment(
    payment_id: int,
    payload: PaymentRefundRequest,
    repository: PaymentRepository = Depends(get_repository),
) -> PaymentResponse:
    payment = await repository.get_payment(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    service = PaymentService(repository)
    refunded = await service.refund(payment, amount=payload.amount)
    return PaymentResponse.model_validate(_serialize_payment(refunded))


@router.patch("/{payment_id}/provider", response_model=PaymentResponse)
async def update_provider_reference(
    payment_id: int,
    payload: PaymentProviderUpdate,
    repository: PaymentRepository = Depends(get_repository),
) -> PaymentResponse:
    payment = await repository.get_payment(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    service = PaymentService(repository)
    updated = await service.update_provider_reference(payment, reference=payload.provider_reference)
    return PaymentResponse.model_validate(_serialize_payment(updated))


@router.get("/{payment_id}/events", response_model=list[PaymentEventResponse])
async def get_payment_events(
    payment_id: int,
    repository: PaymentRepository = Depends(get_repository),
) -> list[PaymentEventResponse]:
    payment = await repository.get_payment(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return [PaymentEventResponse.model_validate(event) for event in _serialize_events(payment)]


@router.delete("/{payment_id}")
async def delete_payment(payment_id: int, repository: PaymentRepository = Depends(get_repository)) -> Response:
    payment = await repository.get_payment(payment_id)
    if payment is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await repository.delete_payment(payment)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
