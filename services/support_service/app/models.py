"""SQLAlchemy models for the support service."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid_str() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    """Base class for support ORM models."""


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal", server_default="normal")
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    conversations: Mapped[list[SupportConversation]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SupportConversation.created_at",
    )
    attachments: Mapped[list["SupportAttachment"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SupportAttachment.created_at",
    )


class SupportConversation(Base):
    __tablename__ = "support_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_type: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ticket: Mapped[SupportTicket] = relationship(back_populates="conversations")


class SupportAttachment(Base):
    __tablename__ = "support_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ticket: Mapped[SupportTicket] = relationship(back_populates="attachments")