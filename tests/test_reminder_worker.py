"""Integration test for the reminder delivery path (at-most-once + no-show sweep).

``process_due_reminder`` opens its own sessions via ``get_session_factory``, so we
point that at a StaticPool in-memory engine (single shared connection) and drive it
with a fake Bot.
"""

from __future__ import annotations

from datetime import timedelta

import pytest_asyncio
from app.database.base import Base
from app.database.models import Event, EventReminder, EventSignup, User
from app.utils.timefmt import now_utc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


@pytest_asyncio.fixture
async def shared_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed(factory, *, signup_status="checked_in", event_status="open"):
    async with factory() as s:
        u = User(telegram_id=42, full_name="Vol", role="volunteer", language="uz")
        s.add(u)
        await s.flush()
        ev = Event(
            title="Cleanup",
            tz="UTC",
            starts_at=now_utc() - timedelta(minutes=10),
            ends_at=now_utc() + timedelta(hours=2),
            capacity=5,
            status=event_status,
        )
        s.add(ev)
        await s.flush()
        s.add(
            EventSignup(event_id=ev.id, user_id=u.id, status=signup_status, checked_in_at=now_utc())
        )
        await s.commit()
        return ev.id


async def test_reminder_sent_once_and_idempotent(shared_factory, fake_redis, monkeypatch):
    from app.services import reminder_service

    monkeypatch.setattr(reminder_service, "get_session_factory", lambda: shared_factory)
    event_id = await _seed(shared_factory)

    bot = FakeBot()
    await reminder_service.process_due_reminder(bot, event_id, "checkout_nudge")
    assert [c[0] for c in bot.sent] == [42]

    # second tick must not re-send (DB reminder row is the fence)
    await reminder_service.process_due_reminder(bot, event_id, "checkout_nudge")
    assert len(bot.sent) == 1

    async with shared_factory() as s:
        row = (await s.execute(select(EventReminder))).scalar_one()
        assert row.status == "sent" and row.kind == "checkout_nudge"


async def test_reminder_skips_cancelled_event(shared_factory, fake_redis, monkeypatch):
    from app.services import reminder_service

    monkeypatch.setattr(reminder_service, "get_session_factory", lambda: shared_factory)
    event_id = await _seed(shared_factory, event_status="cancelled")

    bot = FakeBot()
    await reminder_service.process_due_reminder_safe(bot, event_id, "t1h")
    assert bot.sent == []


async def test_t1h_reminder_targets_registered(shared_factory, fake_redis, monkeypatch):
    from app.services import reminder_service

    monkeypatch.setattr(reminder_service, "get_session_factory", lambda: shared_factory)
    event_id = await _seed(shared_factory, signup_status="registered")

    bot = FakeBot()
    await reminder_service.process_due_reminder(bot, event_id, "t1h")
    assert [c[0] for c in bot.sent] == [42]


async def test_reminder_failure_dead_letters(shared_factory, fake_redis, monkeypatch):
    from app.config import get_settings
    from app.services import reminder_service

    settings = get_settings()
    monkeypatch.setattr(settings, "news_max_retries", 0)
    monkeypatch.setattr(settings, "news_retry_base_delay_sec", 0.0)
    monkeypatch.setattr(reminder_service, "get_session_factory", lambda: shared_factory)
    event_id = await _seed(shared_factory)

    class BadBot:
        async def send_message(self, *a, **k):
            raise RuntimeError("boom")

    await reminder_service.process_due_reminder(BadBot(), event_id, "checkout_nudge")
    async with shared_factory() as s:
        row = (await s.execute(select(EventReminder))).scalar_one()
        assert row.status == "dead_letter"
    assert await fake_redis.llen(settings.reminders_dlq_key) == 1
