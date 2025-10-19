"""HTTP routes for catalog product management."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..dependencies import get_repository
from ..repository import CatalogRepository
from ..schemas import ProductCreate, ProductListResponse, ProductResponse, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


def _to_price_cents(amount: Decimal) -> int:
    """Convert a decimal currency amount into integer cents."""

    quantized = (amount * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
    return int(quantized)


def _serialize_product(product) -> dict[str, object]:
    price = (Decimal(product.price_cents) / Decimal("100")).quantize(Decimal("0.01"))
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "price": price,
        "currency": product.currency,
        "isActive": product.is_active,
        "categories": [category.name for category in product.categories],
        "createdAt": product.created_at,
        "updatedAt": product.updated_at,
    }


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    repository: CatalogRepository = Depends(get_repository),
) -> ProductResponse:
    existing = await repository.get_by_sku(payload.sku)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SKU already exists")

    product = await repository.create_product(
        sku=payload.sku,
        name=payload.name,
        description=payload.description,
        price_cents=_to_price_cents(payload.price),
        currency=payload.currency,
        is_active=payload.is_active,
        categories=payload.categories,
    )
    return ProductResponse.model_validate(_serialize_product(product))


@router.get("", response_model=ProductListResponse)
async def list_products(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category: str | None = Query(default=None),
    only_active: bool = Query(default=False, alias="onlyActive"),
    repository: CatalogRepository = Depends(get_repository),
) -> ProductListResponse:
    products, total = await repository.list_products(
        limit=limit,
        offset=offset,
        category=category.strip() if category else None,
        only_active=only_active,
    )
    items = [ProductResponse.model_validate(_serialize_product(product)) for product in products]
    return ProductListResponse(items=items, total=total)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    repository: CatalogRepository = Depends(get_repository),
) -> ProductResponse:
    product = await repository.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return ProductResponse.model_validate(_serialize_product(product))


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    repository: CatalogRepository = Depends(get_repository),
) -> ProductResponse:
    product = await repository.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    updated = await repository.update_product(
        product,
        name=payload.name,
        description=payload.description,
        price_cents=_to_price_cents(payload.price) if payload.price is not None else None,
        currency=payload.currency,
        is_active=payload.is_active,
        categories=payload.categories,
    )
    return ProductResponse.model_validate(_serialize_product(updated))


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    repository: CatalogRepository = Depends(get_repository),
) -> Response:
    product = await repository.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    await repository.delete_product(product)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
