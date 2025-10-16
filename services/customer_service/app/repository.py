"""Persistence layer for customer service."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CustomerAddress, CustomerProfile, CustomerSegment


class CustomerRepository:
    """Data access helpers for Customer entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_customer(
        self,
        *,
        email: str,
        full_name: str,
        phone_number: str | None,
        preferred_language: str | None,
        addresses: Iterable[CustomerAddress],
    ) -> CustomerProfile:
        profile = CustomerProfile(
            email=email,
            full_name=full_name,
            phone_number=phone_number,
            preferred_language=preferred_language,
            addresses=list(addresses),
        )
        self.session.add(profile)
        await self.session.flush()
        await self.session.refresh(
            profile,
            attribute_names=["addresses", "segments", "created_at", "updated_at"],
        )
        return profile

    async def get_customer(self, customer_id: int) -> CustomerProfile | None:
        result = await self.session.execute(
            select(CustomerProfile).where(CustomerProfile.id == customer_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> CustomerProfile | None:
        result = await self.session.execute(select(CustomerProfile).where(CustomerProfile.email == email))
        return result.scalar_one_or_none()

    async def update_customer(
        self,
        profile: CustomerProfile,
        *,
        full_name: str | None,
        phone_number: str | None,
        preferred_language: str | None,
        addresses: Iterable[CustomerAddress] | None,
    ) -> CustomerProfile:
        if full_name is not None:
            profile.full_name = full_name
        if phone_number is not None:
            profile.phone_number = phone_number
        if preferred_language is not None:
            profile.preferred_language = preferred_language
        if addresses is not None:
            profile.addresses.clear()
            for address in addresses:
                profile.addresses.append(address)

        await self.session.flush()
        await self.session.refresh(
            profile,
            attribute_names=["addresses", "segments", "updated_at"],
        )
        return profile

    async def assign_segment(self, profile: CustomerProfile, segment: str) -> CustomerSegment:
        entry = CustomerSegment(segment=segment, customer=profile)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def remove_segments(self, profile: CustomerProfile) -> None:
        for segment in list(profile.segments):
            await self.session.delete(segment)
        await self.session.flush()

    async def delete_customer(self, profile: CustomerProfile) -> None:
        await self.session.delete(profile)
        await self.session.flush()