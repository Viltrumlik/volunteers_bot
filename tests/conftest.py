"""Shared test fixtures.

Settings env vars are set before any app module is imported so ``get_settings()``
validates. The DB fixture uses in-memory SQLite; the Redis fixture uses fakeredis
(with lupa for Lua/EVAL) so the atomic rate-limiter and fence-lock run unchanged.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKENtesttoken_TESTTOKENtesttoken")
os.environ.setdefault("ADMIN_GROUP_ID", "-1001234567890")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("LOG_HASH_SALT", "test-salt")

from datetime import timedelta

import app.database.models as models  # noqa: F401  (register tables)
import pytest
import pytest_asyncio
from app.database.base import Base
from app.database.models import Event, User
from app.utils.timefmt import now_utc
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def fake_redis(monkeypatch):
    import app.infrastructure.redis_connection as rc
    import fakeredis.aioredis as fa

    r = fa.FakeRedis(decode_responses=True)
    monkeypatch.setattr(rc, "_redis", r)
    yield r
    await r.aclose()


@pytest.fixture
def make_user(session):
    counter = {"n": 0}

    async def _make(role: str = "volunteer", **kw) -> User:
        counter["n"] += 1
        u = User(
            telegram_id=kw.pop("telegram_id", 1000 + counter["n"]),
            full_name=kw.pop("full_name", f"User {counter['n']}"),
            role=role,
            **kw,
        )
        session.add(u)
        await session.flush()
        return u

    return _make


@pytest.fixture
def make_event(session):
    async def _make(
        *, capacity: int = 2, hours_from_now: int = 2, duration_h: int = 3, **kw
    ) -> Event:
        starts = now_utc() + timedelta(hours=hours_from_now)
        e = Event(
            title=kw.pop("title", "Cleanup"),
            description=kw.pop("description", ""),
            location=kw.pop("location", "Park"),
            tz=kw.pop("tz", "UTC"),
            starts_at=starts,
            ends_at=starts + timedelta(hours=duration_h),
            capacity=capacity,
            status=kw.pop("status", "open"),
            **kw,
        )
        session.add(e)
        await session.flush()
        return e

    return _make
