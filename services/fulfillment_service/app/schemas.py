"""Pydantic schemas for the fulfillment service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ShipmentTaskCreate(BaseModel):
    task_type: str = Field(alias="taskType", min_length=1, max_length=24)
    status: str | None = Field(default=None, max_length=24)
    assigned_to: str | None = Field(default=None, alias="assignedTo", max_length=64)
    deadline: datetime | None = None
    payload: dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("status")
    @classmethod
    def _normalize_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        return cleaned or None


class ShipmentTaskResponse(BaseModel):
    id: int
    task_type: str = Field(alias="taskType")
    status: str
    assigned_to: str | None = Field(default=None, alias="assignedTo")
    deadline: datetime | None
    payload: dict[str, Any] | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ShipmentEventResponse(BaseModel):
    id: int
    type: str
    payload: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ShipmentCreate(BaseModel):
    order_id: int = Field(alias="orderId", ge=1)
    fulfillment_center_id: int = Field(alias="fulfillmentCenterId", ge=1)
    carrier: str = Field(min_length=1, max_length=32)
    service_level: str = Field(alias="serviceLevel", min_length=1, max_length=32)
    tracking_number: str | None = Field(default=None, alias="trackingNumber", max_length=64)
    estimated_delivery: datetime | None = Field(default=None, alias="estimatedDelivery")
    tasks: list[ShipmentTaskCreate] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class ShipmentResponse(BaseModel):
    id: int
    order_id: int = Field(alias="orderId")
    fulfillment_center_id: int = Field(alias="fulfillmentCenterId")
    carrier: str
    service_level: str = Field(alias="serviceLevel")
    status: str
    tracking_number: str | None = Field(alias="trackingNumber")
    shipped_at: datetime | None = Field(default=None, alias="shippedAt")
    delivered_at: datetime | None = Field(default=None, alias="deliveredAt")
    estimated_delivery: datetime | None = Field(default=None, alias="estimatedDelivery")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    tasks: list[ShipmentTaskResponse]

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class ShipmentListResponse(BaseModel):
    items: list[ShipmentResponse]
    total: int


class ShipmentStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=255)
    tracking_number: str | None = Field(default=None, alias="trackingNumber", max_length=64)
    estimated_delivery: datetime | None = Field(default=None, alias="estimatedDelivery")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("status")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        return value.strip().lower()


class ShipmentEventListResponse(BaseModel):
    items: list[ShipmentEventResponse]


class TrackingResponse(BaseModel):
    shipment: ShipmentResponse
    events: list[ShipmentEventResponse]


class ReturnCreate(BaseModel):
    order_id: int = Field(alias="orderId", ge=1)
    shipment_id: int | None = Field(default=None, alias="shipmentId", ge=1)
    reason: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(populate_by_name=True)


class ReturnResponse(BaseModel):
    id: int
    order_id: int = Field(alias="orderId")
    shipment_id: int | None = Field(default=None, alias="shipmentId")
    authorization_code: str = Field(alias="authorizationCode")
    status: str
    reason: str | None
    requested_at: datetime = Field(alias="requestedAt")
    processed_at: datetime | None = Field(default=None, alias="processedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)