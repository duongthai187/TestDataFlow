"""HTTP routes for order management."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..dependencies import get_repository
from ..repository import OrderRepository
from ..schemas import (
    OrderCreate,
    OrderEventResponse,
    OrderListResponse,
    OrderResponse,
    OrderUpdateStatus,
)
from ..services import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


def _serialize_order(order) -> dict[str, object]:
    return {
        "id": order.id,
        "customerId": order.customer_id,
        "status": order.status,
        "currency": order.currency,
        "subtotal": (Decimal(order.subtotal_cents) / Decimal("100")).quantize(Decimal("0.01")),
        "discountTotal": (Decimal(order.discount_total_cents) / Decimal("100")).quantize(Decimal("0.01")),
        "shippingTotal": (Decimal(order.shipping_total_cents) / Decimal("100")).quantize(Decimal("0.01")),
        "taxTotal": (Decimal(order.tax_total_cents) / Decimal("100")).quantize(Decimal("0.01")),
        "grandTotal": (Decimal(order.grand_total_cents) / Decimal("100")).quantize(Decimal("0.01")),
        "isPaid": order.is_paid,
        "items": [
            {
                "id": item.id,
                "sku": item.sku,
                "name": item.name,
                "quantity": item.quantity,
                "unitPrice": (Decimal(item.unit_price_cents) / Decimal("100")).quantize(Decimal("0.01")),
                "discountAmount": (Decimal(item.discount_amount_cents) / Decimal("100")).quantize(Decimal("0.01")),
                "taxAmount": (Decimal(item.tax_amount_cents) / Decimal("100")).quantize(Decimal("0.01")),
                "createdAt": item.created_at,
                "updatedAt": item.updated_at,
            }
            for item in order.items
        ],
        "createdAt": order.created_at,
        "updatedAt": order.updated_at,
    }


def _serialize_events(order) -> list[dict[str, object]]:
    return [
        {
            "type": event.type,
            "payload": event.payload,
            "createdAt": event.created_at,
        }
        for event in order.events
    ]


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    repository: OrderRepository = Depends(get_repository),
) -> OrderResponse:
    service = OrderService(repository)
    order = await service.create_order(payload)
    return OrderResponse.model_validate(_serialize_order(order))


@router.get("", response_model=OrderListResponse)
async def list_orders(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    customer_id: int | None = Query(default=None, alias="customerId"),
    status_filter: str | None = Query(default=None, alias="status"),
    repository: OrderRepository = Depends(get_repository),
) -> OrderListResponse:
    orders, total = await repository.list_orders(
        customer_id=customer_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    items = [OrderResponse.model_validate(_serialize_order(order)) for order in orders]
    return OrderListResponse(items=items, total=total)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: int, repository: OrderRepository = Depends(get_repository)) -> OrderResponse:
    order = await repository.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderResponse.model_validate(_serialize_order(order))


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int,
    payload: OrderUpdateStatus,
    repository: OrderRepository = Depends(get_repository),
) -> OrderResponse:
    order = await repository.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    service = OrderService(repository)
    updated = await service.update_status(order, status=payload.status)
    return OrderResponse.model_validate(_serialize_order(updated))


@router.post("/{order_id}/payments/capture", response_model=OrderResponse)
async def capture_payment(order_id: int, repository: OrderRepository = Depends(get_repository)) -> OrderResponse:
    order = await repository.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    service = OrderService(repository)
    updated = await service.mark_paid(order)
    return OrderResponse.model_validate(_serialize_order(updated))


@router.get("/{order_id}/events", response_model=list[OrderEventResponse])
async def get_order_events(order_id: int, repository: OrderRepository = Depends(get_repository)):
    order = await repository.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return [OrderEventResponse.model_validate(event) for event in _serialize_events(order)]


@router.delete("/{order_id}")
async def delete_order(order_id: int, repository: OrderRepository = Depends(get_repository)) -> Response:
    order = await repository.get_order(order_id)
    if order is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await repository.delete_order(order)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
