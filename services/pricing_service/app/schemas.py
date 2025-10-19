"""Pydantic schemas for the pricing service."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class PriceRuleBase(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    region: str | None = Field(default=None, max_length=32)
    currency: str = Field(min_length=3, max_length=3)
    price: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    priority: int = Field(default=100, ge=0, le=1000)
    start_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="startAt")
    end_at: datetime | None = Field(default=None, alias="endAt")
    is_active: bool = Field(default=True, alias="isActive")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("sku")
    @classmethod
    def _clean_sku(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "sku must be non-empty"
            raise ValueError(msg)
        return cleaned

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("region")
    @classmethod
    def _normalize_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        return cleaned or None


class PriceRuleCreate(PriceRuleBase):
    pass


class PriceRuleUpdate(BaseModel):
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    price: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=12, decimal_places=2)
    priority: int | None = Field(default=None, ge=0, le=1000)
    start_at: datetime | None = Field(default=None, alias="startAt")
    end_at: datetime | None = Field(default=None, alias="endAt")
    is_active: bool | None = Field(default=None, alias="isActive")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().upper()


class PriceRuleResponse(PriceRuleBase):
    id: PositiveInt
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class PriceRuleListResponse(BaseModel):
    items: list[PriceRuleResponse]
    total: int


class PriceResolutionResponse(BaseModel):
    rule: PriceRuleResponse
    price: Decimal
