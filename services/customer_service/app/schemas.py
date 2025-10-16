"""Pydantic schemas for customer API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Address(BaseModel):
    label: Optional[str] = None
    line1: str
    line2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: Optional[str] = Field(default=None, alias="postalCode")
    country: str

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class CustomerCreate(BaseModel):
    email: str
    full_name: str = Field(alias="fullName")
    phone_number: Optional[str] = Field(default=None, alias="phoneNumber")
    preferred_language: Optional[str] = Field(default=None, alias="preferredLanguage")
    addresses: list[Address] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if "@" not in value or value.count("@") != 1:
            msg = "invalid email format"
            raise ValueError(msg)
        local, domain = value.split("@")
        if not local or not domain or "." not in domain:
            msg = "invalid email format"
            raise ValueError(msg)
        return value


class CustomerUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, alias="fullName")
    phone_number: Optional[str] = Field(default=None, alias="phoneNumber")
    preferred_language: Optional[str] = Field(default=None, alias="preferredLanguage")
    addresses: Optional[list[Address]] = None

    model_config = ConfigDict(populate_by_name=True)


class CustomerResponse(BaseModel):
    id: int
    email: str
    full_name: str = Field(alias="fullName")
    phone_number: Optional[str] = Field(default=None, alias="phoneNumber")
    preferred_language: Optional[str] = Field(default=None, alias="preferredLanguage")
    addresses: list[Address]
    segments: list[str]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class SegmentAssignment(BaseModel):
    segment: str


class CustomerSegmentResponse(BaseModel):
    customer_id: int = Field(alias="customerId")
    segment: str
    assigned_at: datetime = Field(alias="assignedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)