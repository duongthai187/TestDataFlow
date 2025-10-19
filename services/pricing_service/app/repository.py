"""Data access helpers for pricing service."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PriceRule


class PricingRepository:
    """Persistence helpers for price rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_price_rule(
        self,
        *,
        sku: str,
        region: str | None,
        currency: str,
        price_cents: int,
        priority: int,
        start_at: datetime,
        end_at: datetime | None,
        is_active: bool,
    ) -> PriceRule:
        rule = PriceRule(
            sku=sku,
            region=region,
            currency=currency,
            price_cents=price_cents,
            priority=priority,
            start_at=start_at,
            end_at=end_at,
            is_active=is_active,
        )
        self.session.add(rule)
        await self.session.flush()
        await self.session.refresh(rule, attribute_names=["created_at", "updated_at"])
        return rule

    async def get_price_rule(self, rule_id: int) -> PriceRule | None:
        result = await self.session.execute(select(PriceRule).where(PriceRule.id == rule_id))
        return result.scalar_one_or_none()

    async def list_price_rules(
        self,
        *,
        limit: int,
        offset: int,
        sku: str | None,
        region: str | None,
        active_only: bool,
        effective_at: datetime | None,
    ) -> tuple[list[PriceRule], int]:
        base: Select[tuple[PriceRule]] = select(PriceRule)
        count: Select[tuple[int]] = select(func.count(func.distinct(PriceRule.id)))

        filters = []
        if sku:
            filters.append(PriceRule.sku == sku)
        if region:
            region_filter = or_(PriceRule.region == region, PriceRule.region.is_(None))
            filters.append(region_filter)
        if active_only:
            filters.append(PriceRule.is_active.is_(True))
        if effective_at:
            filters.append(
                and_(
                    PriceRule.start_at <= effective_at,
                    or_(PriceRule.end_at.is_(None), PriceRule.end_at >= effective_at),
                )
            )

        if filters:
            base = base.where(and_(*filters))
            count = count.where(and_(*filters))

        base = base.order_by(PriceRule.priority.asc(), PriceRule.start_at.desc(), PriceRule.id.asc())

        total_result = await self.session.execute(count)
        total = total_result.scalar_one()

        rules_result = await self.session.execute(base.offset(offset).limit(limit))
        rules = list(rules_result.scalars().unique())
        return rules, total

    async def update_price_rule(
        self,
        rule: PriceRule,
        *,
        currency: str | None,
        price_cents: int | None,
        priority: int | None,
        start_at: datetime | None,
        end_at: datetime | None,
        is_active: bool | None,
    ) -> PriceRule:
        if currency is not None:
            rule.currency = currency
        if price_cents is not None:
            rule.price_cents = price_cents
        if priority is not None:
            rule.priority = priority
        if start_at is not None:
            rule.start_at = start_at
        if end_at is not None:
            rule.end_at = end_at
        if is_active is not None:
            rule.is_active = is_active

        await self.session.flush()
        await self.session.refresh(rule, attribute_names=["updated_at"])
        return rule

    async def delete_price_rule(self, rule: PriceRule) -> None:
        await self.session.delete(rule)
        await self.session.flush()

    async def resolve_price(
        self,
        *,
        sku: str,
        region: str | None,
        effective_at: datetime | None,
    ) -> PriceRule | None:
        timestamp = effective_at or datetime.now(timezone.utc)

        query = (
            select(PriceRule)
            .where(
                PriceRule.sku == sku,
                PriceRule.is_active.is_(True),
                PriceRule.start_at <= timestamp,
                or_(PriceRule.end_at.is_(None), PriceRule.end_at >= timestamp),
                or_(PriceRule.region == region, PriceRule.region.is_(None)),
            )
            .order_by(PriceRule.priority.asc(), PriceRule.region.desc(), PriceRule.start_at.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
