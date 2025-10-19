"""Pydantic schemas for notification service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationCreate(BaseModel):
    recipient: str = Field(min_length=1, max_length=255)
    channel: str = Field(min_length=1, max_length=32)
    subject: str | None = Field(default=None, max_length=255)
    body: str = Field(min_length=1)
    template: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] | None = None
    send_after: datetime | None = Field(default=None, alias="sendAfter")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("recipient", "channel", "template", "subject")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned


class NotificationResponse(BaseModel):
    id: int
    recipient: str
    channel: str
    subject: str | None
    body: str
    template: str | None
    metadata: dict[str, Any] | None
    status: str
    error_message: str | None = Field(default=None, alias="errorMessage")
    send_after: datetime | None = Field(default=None, alias="sendAfter")
    sent_at: datetime | None = Field(default=None, alias="sentAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int


class NotificationFailRequest(BaseModel):
    message: str = Field(min_length=1, max_length=255)


class NotificationRescheduleRequest(BaseModel):
    send_after: datetime | None = Field(alias="sendAfter")

    model_config = ConfigDict(populate_by_name=True)


class NotificationEventResponse(BaseModel):
    type: str
    payload: str
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class PreferenceEntry(BaseModel):
    channel: str = Field(min_length=1, max_length=32)
    opt_in: bool = Field(alias="optIn")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("channel")
    @classmethod
    def _normalize_channel(cls, value: str) -> str:
        return value.strip().lower()


class PreferenceResponse(BaseModel):
    customer_id: int = Field(alias="customerId")
    preferences: list[PreferenceEntry]

    model_config = ConfigDict(populate_by_name=True)


class PreferenceUpdate(BaseModel):
    preferences: list[PreferenceEntry]

    @field_validator("preferences")
    @classmethod
    def _ensure_unique_channels(cls, entries: list[PreferenceEntry]) -> list[PreferenceEntry]:
        seen: set[str] = set()
        unique: list[PreferenceEntry] = []
        for entry in entries:
            channel = entry.channel.lower()
            if channel in seen:
                raise ValueError("Duplicate channel entries are not allowed")
            seen.add(channel)
            unique.append(entry)
        return unique


class TemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    channel: str = Field(min_length=1, max_length=32)
    locale: str = Field(min_length=2, max_length=10, default="en-us")
    version: int = Field(default=1, ge=1)
    subject: str | None = Field(default=None)
    body: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("channel")
    @classmethod
    def _channel_lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("locale")
    @classmethod
    def _normalize_locale(cls, value: str) -> str:
        normalized = value.strip().lower().replace("_", "-")
        return normalized


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    channel: str | None = Field(default=None, max_length=32)
    locale: str | None = Field(default=None, max_length=10)
    version: int | None = Field(default=None, ge=1)
    subject: str | None = None
    body: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] | None = Field(default=None)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("channel")
    @classmethod
    def _lower_optional_channel(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

    @field_validator("locale")
    @classmethod
    def _normalize_optional_locale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower().replace("_", "-")


class TemplateResponse(BaseModel):
    id: str
    name: str
    channel: str
    locale: str
    version: int
    subject: str | None
    body: str
    metadata: dict[str, Any] | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class TemplateListResponse(BaseModel):
    items: list[TemplateResponse]
    total: int


class TemplateFilters(BaseModel):
    name: str | None = None
    channel: str | None = None
    locale: str | None = None

    @field_validator("name")
    @classmethod
    def _strip_filter_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("channel")
    @classmethod
    def _lower_filter_channel(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

    @field_validator("locale")
    @classmethod
    def _filter_locale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower().replace("_", "-")


class BatchRecipient(BaseModel):
    recipient: str = Field(min_length=1, max_length=255)
    metadata: dict[str, Any] | None = None

    @field_validator("recipient")
    @classmethod
    def _normalize_recipient(cls, value: str) -> str:
        return value.strip()


class BatchNotificationRequest(BaseModel):
    template_id: str = Field(alias="templateId")
    recipients: list[BatchRecipient] = Field(min_length=1)
    scheduled_for: datetime | None = Field(default=None, alias="scheduledFor")

    model_config = ConfigDict(populate_by_name=True)


class NotificationJobResponse(BaseModel):
    id: int
    template_id: str | None = Field(default=None, alias="templateId")
    status: str
    scheduled_for: datetime | None = Field(default=None, alias="scheduledFor")
    total_count: int = Field(alias="totalCount")
    processed_count: int = Field(alias="processedCount")
    error_message: str | None = Field(default=None, alias="errorMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class NotificationJobListResponse(BaseModel):
    items: list[NotificationJobResponse]
    total: int


class NotificationJobDetailResponse(NotificationJobResponse):
    notifications: list[NotificationResponse]
