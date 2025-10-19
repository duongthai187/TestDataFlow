"""Pydantic schemas for inventory service."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, NonNegativeInt, field_validator


class InventoryCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    location: str | None = Field(default=None, max_length=64)
    quantity_on_hand: NonNegativeInt = Field(default=0, alias="quantityOnHand")
    safety_stock: NonNegativeInt = Field(default=0, alias="safetyStock")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("sku")
    @classmethod
    def _strip_sku(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "sku must be non-empty"
            raise ValueError(msg)
        return cleaned

    @field_validator("location")
    @classmethod
    def _strip_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class InventoryAdjust(BaseModel):
    quantity_on_hand: NonNegativeInt = Field(alias="quantityOnHand")
    safety_stock: NonNegativeInt | None = Field(default=None, alias="safetyStock")

    model_config = ConfigDict(populate_by_name=True)


class InventoryReservation(BaseModel):
    quantity: PositiveInt


class InventoryResponse(BaseModel):
    id: PositiveInt
    sku: str
    location: str | None
    quantity_on_hand: int = Field(alias="quantityOnHand")
    quantity_reserved: int = Field(alias="quantityReserved")
    available: int
    safety_stock: int = Field(alias="safetyStock")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class InventoryListResponse(BaseModel):
    items: list[InventoryResponse]
    total: int


class InventoryEventResponse(BaseModel):
    type: str
    payload: str
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
