"""Dependency wiring for the catalog service."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.common import lifespan_session

from .repository import CatalogRepository


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession for the current request lifecycle."""

    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with lifespan_session(session_factory) as session:
        yield session


def get_repository(session: AsyncSession = Depends(get_session)) -> CatalogRepository:
    """Provide a repository bound to the active session."""

    return CatalogRepository(session)
