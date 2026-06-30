"""Distributed locks with a fence token (SET NX + Lua compare-and-delete release).

Two variants, differing only in their behaviour when Redis is unreachable:

* :func:`redis_lock` — *best-effort*: yields ``True`` if Redis is down. Safe only for
  critical sections that have an independent idempotency backstop (e.g. per-recipient
  news/reminder delivery, which is deduped by a UNIQUE delivery row).
* :func:`redis_lock_strict` — *fail-closed*: yields ``False`` if Redis is down. Use for
  singleton sections that must not run concurrently and have no other guard
  (e.g. the reminder scheduler tick).

Both release the lock only if we still own it (token match), so a lock whose TTL
expired mid-section can never be deleted out from under the worker that re-acquired it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

logger = logging.getLogger(__name__)

# KEYS[1]=lock key, ARGV[1]=our token. Delete only if the stored token is ours.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


@asynccontextmanager
async def _acquire(key: str, *, ttl_sec: int, fail_open: bool) -> AsyncIterator[bool]:
    from app.infrastructure.redis_connection import get_redis

    try:
        r = await get_redis()
    except Exception as exc:  # connection error
        logger.warning("lock %s: redis unavailable (%s); fail_open=%s", key, exc, fail_open)
        yield fail_open
        return

    if r is None:
        yield fail_open
        return

    token = uuid.uuid4().hex
    try:
        acquired = bool(await r.set(key, token, nx=True, ex=ttl_sec))
    except Exception as exc:
        logger.warning("lock %s: acquire failed (%s); fail_open=%s", key, exc, fail_open)
        yield fail_open
        return

    try:
        yield acquired
    finally:
        if acquired:
            try:
                await r.eval(_RELEASE_LUA, 1, key, token)  # type: ignore[no-untyped-call]
            except Exception as exc:
                logger.debug("lock release %s: %s", key, exc)


def redis_lock(key: str, *, ttl_sec: int = 120) -> AbstractAsyncContextManager[bool]:
    """Best-effort lock (fail-open). Pair with an independent idempotency guard."""
    return _acquire(key, ttl_sec=ttl_sec, fail_open=True)


def redis_lock_strict(key: str, *, ttl_sec: int = 30) -> AbstractAsyncContextManager[bool]:
    """Fail-closed lock for singleton sections with no other guard."""
    return _acquire(key, ttl_sec=ttl_sec, fail_open=False)
