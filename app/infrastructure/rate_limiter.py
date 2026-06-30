"""Atomic sliding-window rate limiter (single Lua script, Redis server clock).

Fixes two audit findings in the old middleware:
* **TOCTOU** — the old code did ``ZREMRANGEBYSCORE`` / ``ZCARD`` / ``ZADD`` as separate
  round-trips, so concurrent updates could exceed the limit. Here it is one script.
* **Clock skew** — it used the client's ``time.time()``. Here ``now`` comes from
  ``redis.call('TIME')`` so every worker shares one monotonic-enough source.

Fails *open* on Redis errors (logs loudly): a Redis outage already breaks FSM, so
blocking every user adds nothing but lost availability.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)

# KEYS[1]=zset key  ARGV[1]=window_sec  ARGV[2]=limit  ARGV[3]=unique member
# Returns 1 if allowed (and records the hit), 0 if over the limit.
_ALLOW_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local n = redis.call('ZCARD', KEYS[1])
if n >= limit then
    return 0
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('EXPIRE', KEYS[1], math.ceil(window) + 1)
return 1
"""


async def allow(user_id: int, *, limit: int, window_sec: float) -> bool:
    """Return ``True`` if this hit is within the per-user sliding window."""
    from app.infrastructure.redis_connection import get_redis

    try:
        r = await get_redis()
        if r is None:
            logger.error("rate limit: redis unavailable; allowing (fail-open)")
            return True
        key = f"rl:sliding:{user_id}"
        res = await r.eval(  # type: ignore[no-untyped-call]
            _ALLOW_LUA, 1, key, str(window_sec), str(limit), uuid.uuid4().hex
        )
        return bool(int(res))
    except Exception as exc:
        logger.exception("rate limit redis error: %s; allowing (fail-open)", exc)
        return True
