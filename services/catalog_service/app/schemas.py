"""Pydantic schemas for the catalog service."""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class ProductBase(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    price: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    is_active: bool = Field(default=True, alias="isActive")
    categories: list[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "name must be non-empty"
            raise ValueError(msg)
        return cleaned

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("categories", mode="before")
    @classmethod
    def _normalize_categories(cls, value):
        if value is None:
            return []
        return value

    @field_validator("categories")
    @classmethod
    def _validate_categories(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(value):
            msg = "Category names must be non-empty"
            raise ValueError(msg)
        return cleaned


class ProductCreate(ProductBase):
    sku: str = Field(min_length=1, max_length=64)

    @field_validator("sku")
    @classmethod
    def _validate_sku(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "sku must be non-empty"
            raise ValueError(msg)
        return cleaned


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    price: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = Field(default=None, alias="isActive")
    categories: list[str] | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            msg = "name must be non-empty"
            raise ValueError(msg)
        return cleaned

    @field_validator("currency")
    @classmethod
    def _clean_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().upper()

    @field_validator("categories")
    @classmethod
    def _clean_categories(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(value):
            msg = "Category names must be non-empty"
            raise ValueError(msg)
        return cleaned


class ProductResponse(ProductBase):
    id: PositiveInt
    sku: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int
