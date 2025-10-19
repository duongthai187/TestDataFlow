"""Dependency helpers for the support service."""

from __future__ import annotations

from collections.abc import AsyncIterator

from typing import cast

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.common import lifespan_session

from .events import SupportEventPublisher
from .repository import SupportRepository
from .storage import AttachmentStorageProtocol
from .timeline import TimelineAggregatorProtocol


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with lifespan_session(session_factory) as session:
        yield session


def get_repository(session: AsyncSession = Depends(get_session)) -> SupportRepository:
    return SupportRepository(session)


def get_timeline_aggregator(request: Request) -> TimelineAggregatorProtocol | None:
    aggregator = getattr(request.app.state, "timeline_aggregator", None)
    if aggregator is None:
        return None
    if hasattr(aggregator, "collect") and hasattr(aggregator, "invalidate"):
        return cast(TimelineAggregatorProtocol, aggregator)
    return None


def get_attachment_storage_optional(request: Request) -> AttachmentStorageProtocol | None:
    storage = getattr(request.app.state, "attachment_storage", None)
    if storage is None:
        return None
    if hasattr(storage, "save") and hasattr(storage, "close"):
        return cast(AttachmentStorageProtocol, storage)
    return None


def get_attachment_storage(request: Request) -> AttachmentStorageProtocol:
    storage = get_attachment_storage_optional(request)
    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Attachment storage is not configured",
        )
    return storage


def get_event_publisher_optional(request: Request) -> SupportEventPublisher | None:
    publisher = getattr(request.app.state, "event_publisher", None)
    if publisher is None:
        return None
    if hasattr(publisher, "case_opened"):
        return cast(SupportEventPublisher, publisher)
    return None


def get_event_publisher(request: Request) -> SupportEventPublisher:
    publisher = get_event_publisher_optional(request)
    if publisher is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event publisher is not configured",
        )
    return publisher