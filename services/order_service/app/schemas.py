"""Pydantic schemas for the order service."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class OrderItemPayload(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    quantity: PositiveInt
    unit_price: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2, alias="unitPrice")
    discount_amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2, alias="discountAmount")
    tax_amount: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2, alias="taxAmount")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("sku", "name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "value must be non-empty"
            raise ValueError(msg)
        return cleaned


class OrderCreate(BaseModel):
    customer_id: PositiveInt = Field(alias="customerId")
    currency: str = Field(min_length=3, max_length=3)
    items: list[OrderItemPayload]
    shipping_total: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2, alias="shippingTotal")
    tax_total: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2, alias="taxTotal")
    discount_total: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2, alias="discountTotal")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class OrderUpdateStatus(BaseModel):
    status: str = Field(min_length=1, max_length=32)


class OrderItemResponse(OrderItemPayload):
    id: PositiveInt
    unit_price: Decimal = Field(alias="unitPrice")
    discount_amount: Decimal = Field(default=Decimal("0"), alias="discountAmount")
    tax_amount: Decimal = Field(default=Decimal("0"), alias="taxAmount")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class OrderResponse(BaseModel):
    id: PositiveInt
    customer_id: PositiveInt = Field(alias="customerId")
    status: str
    currency: str
    subtotal: Decimal
    discount_total: Decimal = Field(alias="discountTotal")
    shipping_total: Decimal = Field(alias="shippingTotal")
    tax_total: Decimal = Field(alias="taxTotal")
    grand_total: Decimal = Field(alias="grandTotal")
    is_paid: bool = Field(alias="isPaid")
    items: list[OrderItemResponse]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int


class OrderEventResponse(BaseModel):
    type: str
    payload: str
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
