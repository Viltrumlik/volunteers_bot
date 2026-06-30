from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


async def incr(name: str, amount: int = 1) -> None:
    try:
        from app.infrastructure.redis_connection import get_redis

        r = await get_redis()
        if r is None:
            return
        await r.incrby(f"metrics:{name}", amount)
    except Exception as e:
        logger.debug("metrics incr fail: %s", e)


async def incr_daily_counter(prefix: str) -> None:
    """Redis key metrics:{prefix}:YYYY-MM-DD (daily totals)."""
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    await incr(f"{prefix}:{day}")


async def record_active_user(telegram_id: int) -> None:
    """HyperLogLog cardinality per UTC day (approximate DAU)."""
    try:
        from app.infrastructure.redis_connection import get_redis

        r = await get_redis()
        if r is None:
            return
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"metrics:active_hll:{day}"
        await r.pfadd(key, str(telegram_id))
        await r.expire(key, 86400 * 10)
    except Exception as e:
        logger.debug("active user metric: %s", e)


async def get_counter(name: str) -> int | None:
    try:
        from app.infrastructure.redis_connection import get_redis

        r = await get_redis()
        if r is None:
            return None
        v = await r.get(f"metrics:{name}")
        return int(v) if v is not None else 0
    except Exception:
        return None


async def pfcount_day(day: str) -> int | None:
    try:
        from app.infrastructure.redis_connection import get_redis

        r = await get_redis()
        if r is None:
            return None
        n = await r.pfcount(f"metrics:active_hll:{day}")
        return int(n)
    except Exception:
        return None
