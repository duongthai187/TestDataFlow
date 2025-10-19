"""Persistence helpers for catalog service."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product, ProductCategory


class CatalogRepository:
    """Data access methods for catalog entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_product(
        self,
        *,
        sku: str,
        name: str,
        description: str | None,
        price_cents: int,
        currency: str,
        is_active: bool,
        categories: Iterable[str],
    ) -> Product:
        product = Product(
            sku=sku,
            name=name,
            description=description,
            price_cents=price_cents,
            currency=currency,
            is_active=is_active,
            categories=[ProductCategory(name=category) for category in categories],
        )
        self.session.add(product)
        await self.session.flush()
        await self.session.refresh(
            product,
            attribute_names=["categories", "created_at", "updated_at"],
        )
        return product

    async def get_product(self, product_id: int) -> Product | None:
        result = await self.session.execute(select(Product).where(Product.id == product_id))
        return result.scalar_one_or_none()

    async def get_by_sku(self, sku: str) -> Product | None:
        result = await self.session.execute(select(Product).where(Product.sku == sku))
        return result.scalar_one_or_none()

    async def list_products(
        self,
        *,
        limit: int,
        offset: int,
        category: str | None,
        only_active: bool,
    ) -> tuple[list[Product], int]:
        base_query: Select[tuple[Product]] = select(Product)
        count_query: Select[tuple[int]] = select(func.count(func.distinct(Product.id)))

        if category:
            base_query = base_query.join(ProductCategory).where(ProductCategory.name == category)
            count_query = count_query.join(ProductCategory).where(ProductCategory.name == category)

        if only_active:
            base_query = base_query.where(Product.is_active.is_(True))
            count_query = count_query.where(Product.is_active.is_(True))

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        result = await self.session.execute(
            base_query.distinct().order_by(Product.id).offset(offset).limit(limit)
        )
        products = list(result.scalars().unique())
        return products, total

    async def update_product(
        self,
        product: Product,
        *,
        name: str | None,
        description: str | None,
        price_cents: int | None,
        currency: str | None,
        is_active: bool | None,
        categories: Iterable[str] | None,
    ) -> Product:
        if name is not None:
            product.name = name
        if description is not None:
            product.description = description
        if price_cents is not None:
            product.price_cents = price_cents
        if currency is not None:
            product.currency = currency
        if is_active is not None:
            product.is_active = is_active
        if categories is not None:
            product.categories.clear()
            for category in categories:
                product.categories.append(ProductCategory(name=category))

        await self.session.flush()
        await self.session.refresh(
            product,
            attribute_names=["categories", "updated_at"],
        )
        return product

    async def delete_product(self, product: Product) -> None:
        await self.session.delete(product)
        await self.session.flush()
