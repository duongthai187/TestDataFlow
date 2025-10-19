"""Pydantic schemas for the support service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationCreate(BaseModel):
    author_type: str = Field(alias="authorType", min_length=1, max_length=16)
    message: str = Field(min_length=1)
    attachment_uri: str | None = Field(default=None, alias="attachmentUri")
    sentiment: str | None = Field(default=None, max_length=16)
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("author_type")
    @classmethod
    def _normalize_author(cls, value: str) -> str:
        return value.strip().lower()


class ConversationResponse(BaseModel):
    id: str
    ticket_id: str = Field(alias="ticketId")
    author_type: str = Field(alias="authorType")
    message: str
    attachment_uri: str | None = Field(default=None, alias="attachmentUri")
    sentiment: str | None
    metadata: dict[str, Any] | None
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class InitialMessage(BaseModel):
    author_type: str = Field(alias="authorType", min_length=1, max_length=16)
    message: str = Field(min_length=1)
    attachment_uri: str | None = Field(default=None, alias="attachmentUri")
    sentiment: str | None = Field(default=None, max_length=16)
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("author_type")
    @classmethod
    def _normalize_author(cls, value: str) -> str:
        return value.strip().lower()


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None)
    customer_id: str | None = Field(default=None, alias="customerId", min_length=1, max_length=36)
    channel: str = Field(min_length=1, max_length=32)
    priority: str | None = Field(default=None, max_length=16)
    assigned_agent_id: str | None = Field(default=None, alias="assignedAgentId", min_length=1, max_length=36)
    context: dict[str, Any] | list[dict[str, Any]] | None = None
    initial_message: InitialMessage | None = Field(default=None, alias="initialMessage")

    model_config = ConfigDict(populate_by_name=True)


class TicketResponse(BaseModel):
    id: str
    subject: str
    description: str | None
    customer_id: str | None = Field(alias="customerId")
    status: str
    priority: str
    channel: str
    assigned_agent_id: str | None = Field(alias="assignedAgentId")
    context: dict[str, Any] | list[dict[str, Any]] | None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class TicketDetailResponse(TicketResponse):
    messages: list[ConversationResponse]
    timeline: list[dict[str, Any]]
    attachments: list["AttachmentResponse"]


class TicketCloseRequest(BaseModel):
    message: str | None = Field(default=None, min_length=1)
    author_type: str | None = Field(default=None, alias="authorType", min_length=1, max_length=16)
    attachment_uri: str | None = Field(default=None, alias="attachmentUri")
    sentiment: str | None = Field(default=None, max_length=16)
    metadata: dict[str, Any] | None = None
    assigned_agent_id: str | None = Field(default=None, alias="assignedAgentId", min_length=1, max_length=36)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("author_type")
    @classmethod
    def _normalize_author(cls, value: str | None) -> str | None:
        return value.strip().lower() if value is not None else None


class AttachmentResponse(BaseModel):
    id: str
    ticket_id: str = Field(alias="ticketId")
    filename: str
    content_type: str = Field(alias="contentType")
    size_bytes: int = Field(alias="sizeBytes")
    uri: str
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class AgentWorkloadResponse(BaseModel):
    agent_id: str = Field(alias="agentId")
    open: int
    pending: int
    resolved: int
    closed: int

    model_config = ConfigDict(populate_by_name=True)
