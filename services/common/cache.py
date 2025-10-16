"""Async Redis helper functions."""

from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

try:  # pragma: no cover - optional dependency handling
    from redis.asyncio import Redis as _Redis
except ModuleNotFoundError:  # pragma: no cover - executed only when redis is unavailable
    _Redis = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis as RedisType
else:  # pragma: no cover - used when dependency absent
    RedisType = Any

from .config import ServiceSettings


_CACHE: Dict[str, RedisType] = {}


def get_redis_client(redis_url: str) -> RedisType:
    """Return a cached Redis client for the given URL."""

    if _Redis is None:
        raise RuntimeError(
            "redis dependency is not installed. Install 'redis' to enable cache support."
        )

    if redis_url not in _CACHE:
        _CACHE[redis_url] = _Redis.from_url(redis_url, decode_responses=True)
    return _CACHE[redis_url]


def resolve_redis(settings: ServiceSettings) -> RedisType | None:
    """Return a Redis client or None if not configured."""

    if not settings.redis_url:
        return None
    return get_redis_client(settings.redis_url)


async def close_redis_connections() -> None:
    """Close all cached Redis connections (used for shutdown/tests)."""

    if _Redis is None:
        _CACHE.clear()
        return

    for redis in _CACHE.values():
        await redis.close()
    _CACHE.clear()
