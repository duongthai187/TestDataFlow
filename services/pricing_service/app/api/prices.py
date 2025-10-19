"""API routes for managing price rules."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from ..dependencies import get_repository
from ..repository import PricingRepository
from ..schemas import (
    PriceResolutionResponse,
    PriceRuleCreate,
    PriceRuleListResponse,
    PriceRuleResponse,
    PriceRuleUpdate,
)

router = APIRouter(prefix="/prices", tags=["prices"])


def _to_cents(amount: Decimal) -> int:
    quantized = (amount * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
    return int(quantized)


def _serialize(rule) -> dict[str, object]:
    price = (Decimal(rule.price_cents) / Decimal("100")).quantize(Decimal("0.01"))
    return {
        "id": rule.id,
        "sku": rule.sku,
        "region": rule.region,
        "currency": rule.currency,
        "price": price,
        "priority": rule.priority,
        "startAt": rule.start_at,
        "endAt": rule.end_at,
        "isActive": rule.is_active,
        "createdAt": rule.created_at,
        "updatedAt": rule.updated_at,
    }


@router.post("", response_model=PriceRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_price_rule(
    payload: PriceRuleCreate,
    repository: PricingRepository = Depends(get_repository),
) -> PriceRuleResponse:
    try:
        rule = await repository.create_price_rule(
            sku=payload.sku,
            region=payload.region,
            currency=payload.currency,
            price_cents=_to_cents(payload.price),
            priority=payload.priority,
            start_at=payload.start_at,
            end_at=payload.end_at,
            is_active=payload.is_active,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Price rule already exists") from exc
    return PriceRuleResponse.model_validate(_serialize(rule))


@router.get("", response_model=PriceRuleListResponse)
async def list_price_rules(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sku: str | None = Query(default=None),
    region: str | None = Query(default=None),
    active_only: bool = Query(default=False, alias="activeOnly"),
    effective_at: datetime | None = Query(default=None, alias="effectiveAt"),
    repository: PricingRepository = Depends(get_repository),
) -> PriceRuleListResponse:
    rules, total = await repository.list_price_rules(
        limit=limit,
        offset=offset,
        sku=sku.strip() if sku else None,
        region=region.strip().lower() if region else None,
        active_only=active_only,
        effective_at=effective_at,
    )
    items = [PriceRuleResponse.model_validate(_serialize(rule)) for rule in rules]
    return PriceRuleListResponse(items=items, total=total)


@router.get("/resolve", response_model=PriceResolutionResponse)
async def resolve_price(
    sku: str = Query(..., min_length=1),
    region: str | None = Query(default=None),
    effective_at: datetime | None = Query(default=None, alias="effectiveAt"),
    repository: PricingRepository = Depends(get_repository),
) -> PriceResolutionResponse:
    rule = await repository.resolve_price(
        sku=sku.strip(),
        region=region.strip().lower() if region else None,
        effective_at=effective_at,
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Price rule not found")

    payload = PriceRuleResponse.model_validate(_serialize(rule))
    price = payload.price
    return PriceResolutionResponse(rule=payload, price=price)


@router.get("/{rule_id}", response_model=PriceRuleResponse)
async def get_price_rule(
    rule_id: int,
    repository: PricingRepository = Depends(get_repository),
) -> PriceRuleResponse:
    rule = await repository.get_price_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Price rule not found")
    return PriceRuleResponse.model_validate(_serialize(rule))


@router.patch("/{rule_id}", response_model=PriceRuleResponse)
async def update_price_rule(
    rule_id: int,
    payload: PriceRuleUpdate,
    repository: PricingRepository = Depends(get_repository),
) -> PriceRuleResponse:
    rule = await repository.get_price_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Price rule not found")

    try:
        updated = await repository.update_price_rule(
            rule,
            currency=payload.currency,
            price_cents=_to_cents(payload.price) if payload.price is not None else None,
            priority=payload.priority,
            start_at=payload.start_at,
            end_at=payload.end_at,
            is_active=payload.is_active,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Price rule already exists") from exc
    return PriceRuleResponse.model_validate(_serialize(updated))


@router.delete("/{rule_id}")
async def delete_price_rule(
    rule_id: int,
    repository: PricingRepository = Depends(get_repository),
) -> Response:
    rule = await repository.get_price_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Price rule not found")
    await repository.delete_price_rule(rule)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
