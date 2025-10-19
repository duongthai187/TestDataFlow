"""Pydantic schemas for the cart service."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class CartItemBase(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    unit_price: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2, alias="unitPrice")
    quantity: PositiveInt

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("sku", "name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "value must be non-empty"
            raise ValueError(msg)
        return cleaned


class CartItemCreate(CartItemBase):
    pass


class CartItemUpdate(BaseModel):
    quantity: PositiveInt | None = None
    unit_price: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=12, decimal_places=2, alias="unitPrice")

    model_config = ConfigDict(populate_by_name=True)


class CartItemResponse(CartItemBase):
    id: PositiveInt
    unit_price: Decimal = Field(alias="unitPrice")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class CartResponse(BaseModel):
    id: PositiveInt
    customer_id: PositiveInt = Field(alias="customerId")
    currency: str
    items: list[CartItemResponse]
    total: Decimal
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class CartTotalsResponse(BaseModel):
    total_items: int = Field(alias="totalItems")
    total_amount: Decimal = Field(alias="totalAmount")


class CartMergeRequest(BaseModel):
    from_customer_id: PositiveInt = Field(alias="fromCustomerId")
    to_customer_id: PositiveInt = Field(alias="toCustomerId")