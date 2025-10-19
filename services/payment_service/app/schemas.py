"""Pydantic schemas for the payment service."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class PaymentCreate(BaseModel):
    customer_id: PositiveInt = Field(alias="customerId")
    order_id: PositiveInt | None = Field(default=None, alias="orderId")
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    payment_method: str = Field(alias="paymentMethod", min_length=1, max_length=64)
    provider_reference: str | None = Field(default=None, alias="providerReference", max_length=128)
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("payment_method")
    @classmethod
    def _strip_method(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "payment method must be non-empty"
            raise ValueError(msg)
        return cleaned


class PaymentUpdateStatus(BaseModel):
    status: str = Field(min_length=1, max_length=32)


class PaymentResponse(BaseModel):
    id: PositiveInt
    customer_id: PositiveInt = Field(alias="customerId")
    order_id: PositiveInt | None = Field(default=None, alias="orderId")
    amount: Decimal
    currency: str
    status: str
    payment_method: str = Field(alias="paymentMethod")
    provider_reference: str | None = Field(default=None, alias="providerReference")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int


class PaymentEventResponse(BaseModel):
    type: str
    payload: str
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class PaymentRefundRequest(BaseModel):
    amount: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        max_digits=12,
        decimal_places=2,
    )


class PaymentProviderUpdate(BaseModel):
    provider_reference: str | None = Field(
        default=None,
        alias="providerReference",
        max_length=128,
    )

    model_config = ConfigDict(populate_by_name=True)
