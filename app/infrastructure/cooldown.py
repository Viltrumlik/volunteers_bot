"""Cross-worker creation cooldown (anti-spam) backed by Redis ``SET NX EX``.

The previous implementation kept cooldowns in a per-process dict, so a user could
bypass it by hitting different workers. ``try_acquire`` is a single atomic command,
so the cooldown holds across the whole fleet.

Fails *open* (allows the action) when Redis is unavailable: the bot already requires
Redis for FSM, so an outage degrades everything — silently locking users out of
ticket/suggestion creation on a Redis blip would be worse than a brief spam window.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def try_acquire(scope: str, user_id: int, seconds: float) -> bool:
    """Atomically claim a cooldown slot.

    Returns ``True`` if the action is allowed (and the cooldown was started),
    ``False`` if the user is still within the cooldown window.
    """
    if seconds <= 0:
        return True
    from app.infrastructure.redis_connection import get_redis

    try:
        r = await get_redis()
        if r is None:
            return True
        key = f"cd:{scope}:{user_id}"
        ok = await r.set(key, "1", nx=True, ex=int(seconds) or 1)
        return bool(ok)
    except Exception as exc:  # availability over strict anti-spam
        logger.warning("cooldown %s/%s: redis error %s; allowing", scope, user_id, exc)
        return True
