"""Async SQLAlchemy helpers shared across services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import ServiceSettings

_ENGINE_CACHE: dict[str, AsyncEngine] = {}
_SESSION_FACTORY_CACHE: dict[str, async_sessionmaker[AsyncSession]] = {}


def create_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """Create or reuse a cached AsyncEngine for the given URL."""

    if database_url in _ENGINE_CACHE:
        return _ENGINE_CACHE[database_url]

    engine = create_async_engine(database_url, pool_pre_ping=True, **kwargs)
    _ENGINE_CACHE[database_url] = engine
    return engine


def get_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Return an async_sessionmaker bound to the cached engine."""

    if database_url in _SESSION_FACTORY_CACHE:
        return _SESSION_FACTORY_CACHE[database_url]

    engine = create_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    _SESSION_FACTORY_CACHE[database_url] = session_factory
    return session_factory


@asynccontextmanager
async def lifespan_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Provide an AsyncSession context for FastAPI dependencies."""

    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def resolve_database_url(settings: ServiceSettings, fallback: str) -> str:
    """Pick database URL from settings or fallback."""

    return settings.database_url or fallback


async def dispose_engines() -> None:
    """Dispose all cached engines (used on shutdown or tests)."""

    for engine in _ENGINE_CACHE.values():
        await engine.dispose()
    _ENGINE_CACHE.clear()
    _SESSION_FACTORY_CACHE.clear()
