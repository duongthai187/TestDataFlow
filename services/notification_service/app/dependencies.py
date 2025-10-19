"""Dependency helpers for notification service."""

from __future__ import annotations

from collections.abc import AsyncIterator

from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.common import lifespan_session

from .repository import NotificationRepository
from .services import NotificationService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with lifespan_session(session_factory) as session:
        yield session


def get_repository(session: AsyncSession = Depends(get_session)) -> NotificationRepository:
    return NotificationRepository(session)


def get_rate_limiter(request: Request) -> Any:
    return getattr(request.app.state, "rate_limiter", None)


def get_provider(request: Request) -> Any:
    return getattr(request.app.state, "notification_provider", None)


def get_event_publisher(request: Request) -> Any:
    return getattr(request.app.state, "event_publisher", None)


def get_notification_service(
    repository: NotificationRepository = Depends(get_repository),
    rate_limiter: Any = Depends(get_rate_limiter),
    provider: Any = Depends(get_provider),
    event_publisher: Any = Depends(get_event_publisher),
) -> NotificationService:
    return NotificationService(
        repository,
        provider=provider,
        rate_limiter=rate_limiter,
        event_publisher=event_publisher,
    )
