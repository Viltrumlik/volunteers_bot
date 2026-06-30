"""Cross-worker cooldown, atomic rate limiter, and fence-token locks."""

from __future__ import annotations

import app.infrastructure.redis_connection as rc
from app.infrastructure import rate_limiter
from app.infrastructure.cooldown import try_acquire
from app.infrastructure.redis_lock import redis_lock, redis_lock_strict


async def test_cooldown_holds_across_calls(fake_redis):
    assert await try_acquire("ticket", 1, 60) is True
    assert await try_acquire("ticket", 1, 60) is False  # still cooling down
    assert await try_acquire("ticket", 2, 60) is True  # different user unaffected


async def test_cooldown_disabled_when_zero(fake_redis):
    assert await try_acquire("ticket", 1, 0) is True
    assert await try_acquire("ticket", 1, 0) is True


async def test_rate_limiter_atomic_window(fake_redis):
    results = [await rate_limiter.allow(7, limit=3, window_sec=60) for _ in range(5)]
    assert results == [True, True, True, False, False]
    # a different user has an independent budget
    assert await rate_limiter.allow(8, limit=3, window_sec=60) is True


async def test_strict_lock_contention(fake_redis):
    async with redis_lock_strict("lk", ttl_sec=30) as a:
        assert a is True
        async with redis_lock_strict("lk", ttl_sec=30) as b:
            assert b is False  # already held


async def test_strict_lock_fail_closed_when_redis_down(monkeypatch):
    async def _none():
        return None

    monkeypatch.setattr(rc, "get_redis", _none)
    async with redis_lock_strict("lk", ttl_sec=30) as got:
        assert got is False  # fail closed


async def test_best_effort_lock_fail_open_when_redis_down(monkeypatch):
    async def _none():
        return None

    monkeypatch.setattr(rc, "get_redis", _none)
    async with redis_lock("lk", ttl_sec=30) as got:
        assert got is True  # fail open (deduped elsewhere)
