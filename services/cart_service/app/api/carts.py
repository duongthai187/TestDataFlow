"""API routes for cart management."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from ..dependencies import get_repository
from ..repository import CartRepository
from ..schemas import (
    CartItemCreate,
    CartItemUpdate,
    CartMergeRequest,
    CartResponse,
    CartTotalsResponse,
)

router = APIRouter(prefix="/carts", tags=["carts"])


def _to_cents(amount: Decimal) -> int:
    return int((amount * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


def _serialize_cart(cart, totals: tuple[int, Decimal]) -> dict[str, object]:
    total_items, total_amount = totals
    return {
        "id": cart.id,
        "customerId": cart.customer_id,
        "currency": cart.currency,
        "items": [
            {
                "id": item.id,
                "sku": item.sku,
                "name": item.name,
                "unitPrice": (Decimal(item.unit_price_cents) / Decimal("100")).quantize(Decimal("0.01")),
                "quantity": item.quantity,
                "createdAt": item.created_at,
                "updatedAt": item.updated_at,
            }
            for item in cart.items
        ],
    "total": total_amount.quantize(Decimal("0.01")),
        "createdAt": cart.created_at,
        "updatedAt": cart.updated_at,
    }


def _serialize_totals(totals: tuple[int, Decimal]) -> dict[str, object]:
    total_items, total_amount = totals
    return {
        "totalItems": total_items,
        "totalAmount": total_amount.quantize(Decimal("0.01")),
    }


@router.get("/{customer_id}", response_model=CartResponse)
async def get_cart(
    customer_id: int = Path(..., ge=1),
    repository: CartRepository = Depends(get_repository),
) -> CartResponse:
    cart = await repository.get_cart(customer_id=customer_id)
    if cart is None:
        cart = await repository.get_or_create_cart(customer_id=customer_id, currency="USD")
    totals = await repository.cart_totals(cart)
    return CartResponse.model_validate(_serialize_cart(cart, totals))


@router.post("/{customer_id}/items", response_model=CartResponse, status_code=status.HTTP_201_CREATED)
async def add_item(
    customer_id: int,
    payload: CartItemCreate,
    repository: CartRepository = Depends(get_repository),
) -> CartResponse:
    cart = await repository.get_or_create_cart(customer_id=customer_id, currency="USD")
    cart = await repository.add_item(
        cart,
        sku=payload.sku,
        name=payload.name,
        unit_price_cents=_to_cents(payload.unit_price),
        quantity=payload.quantity,
    )
    totals = await repository.cart_totals(cart)
    return CartResponse.model_validate(_serialize_cart(cart, totals))


@router.patch("/{customer_id}/items/{sku}", response_model=CartResponse)
async def update_item(
    customer_id: int,
    sku: str,
    payload: CartItemUpdate,
    repository: CartRepository = Depends(get_repository),
) -> CartResponse:
    cart = await repository.get_cart(customer_id=customer_id)
    if cart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found")

    try:
        cart = await repository.update_item(
            cart,
            sku=sku,
            unit_price_cents=_to_cents(payload.unit_price) if payload.unit_price is not None else None,
            quantity=payload.quantity,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found") from exc

    totals = await repository.cart_totals(cart)
    return CartResponse.model_validate(_serialize_cart(cart, totals))


@router.delete("/{customer_id}/items/{sku}", response_model=CartResponse)
async def remove_item(
    customer_id: int,
    sku: str,
    repository: CartRepository = Depends(get_repository),
) -> CartResponse:
    cart = await repository.get_cart(customer_id=customer_id)
    if cart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found")

    try:
        cart = await repository.remove_item(cart, sku=sku)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found") from exc

    totals = await repository.cart_totals(cart)
    return CartResponse.model_validate(_serialize_cart(cart, totals))


@router.delete("/{customer_id}")
async def clear_cart(
    customer_id: int,
    repository: CartRepository = Depends(get_repository),
) -> Response:
    cart = await repository.get_cart(customer_id=customer_id)
    if cart is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await repository.clear_cart(cart)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{customer_id}/totals", response_model=CartTotalsResponse)
async def get_cart_totals(
    customer_id: int,
    repository: CartRepository = Depends(get_repository),
) -> CartTotalsResponse:
    cart = await repository.get_cart(customer_id=customer_id)
    if cart is None:
        return CartTotalsResponse.model_validate({"totalItems": 0, "totalAmount": Decimal("0.00")})
    totals = await repository.cart_totals(cart)
    return CartTotalsResponse.model_validate(_serialize_totals(totals))


@router.post("/merge", response_model=CartResponse)
async def merge_carts(
    payload: CartMergeRequest,
    repository: CartRepository = Depends(get_repository),
) -> CartResponse:
    source = await repository.get_cart(customer_id=payload.from_customer_id)
    target = await repository.get_or_create_cart(customer_id=payload.to_customer_id, currency="USD")

    if source is None:
        totals = await repository.cart_totals(target)
        return CartResponse.model_validate(_serialize_cart(target, totals))

    for item in list(source.items):
        await repository.add_item(
            target,
            sku=item.sku,
            name=item.name,
            unit_price_cents=item.unit_price_cents,
            quantity=item.quantity,
        )
    await repository.clear_cart(source)

    totals = await repository.cart_totals(target)
    return CartResponse.model_validate(_serialize_cart(target, totals))
