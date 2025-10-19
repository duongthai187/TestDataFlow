"""Redis-backed rate limiting helpers for notification service."""

from __future__ import annotations

from typing import Any

from .metrics import NOTIFICATION_RATE_LIMIT_ERRORS_TOTAL

class RateLimiter:
    """Simple token bucket rate limiter keyed by channel."""

    def __init__(
        self,
        redis_client: Any | None,
        *,
        key_prefix: str = "notification_rate",
        limit: int = 120,
        window_seconds: int = 60,
    ) -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._limit = max(limit, 1)
        self._window = max(window_seconds, 1)

    async def allow(self, channel: str, *, amount: int = 1) -> bool:
        """Return True if the channel may proceed with the given amount."""

        if amount <= 0:
            return True
        if self._redis is None:
            return True

        key = f"{self._key_prefix}:{channel.lower()}"
        try:
            count = await self._redis.incrby(key, amount)
        except Exception:
            NOTIFICATION_RATE_LIMIT_ERRORS_TOTAL.labels(operation="incrby").inc()
            return True
        if count == amount:
            try:
                await self._redis.expire(key, self._window)
            except Exception:
                NOTIFICATION_RATE_LIMIT_ERRORS_TOTAL.labels(operation="expire").inc()
        if count > self._limit:
            try:
                await self._redis.decrby(key, amount)
            except Exception:
                NOTIFICATION_RATE_LIMIT_ERRORS_TOTAL.labels(operation="decrby").inc()
                return True
            return False
        return True