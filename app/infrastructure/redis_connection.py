"""Shared async Redis client.

Redis is required by the app (FSM, rate limits, cooldowns, queues, metrics), but
helpers here degrade to ``None`` when it is genuinely unavailable so callers can
choose fail-open vs fail-closed per use-case.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.config import get_settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_redis: Redis[Any] | None = None


async def get_redis() -> Redis[Any] | None:
    """Return the shared client, or ``None`` if REDIS_URL is unset."""
    global _redis
    url = (get_settings().redis_url or "").strip()
    if not url:
        return None
    if _redis is None:
        import redis.asyncio as redis

        _redis = redis.from_url(url, decode_responses=True)
        logger.info("Redis client initialized")
    return _redis


async def check_redis() -> None:
    """Fail-fast connectivity probe used at startup."""
    r = await get_redis()
    if r is None:
        raise RuntimeError("REDIS_URL is not configured")
    await r.ping()


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()  # type: ignore[attr-defined]
        finally:
            _redis = None
            logger.info("Redis client closed")
