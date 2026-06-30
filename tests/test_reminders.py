"""Reminder scheduling (ZSET) and idempotent reminder/ledger rows."""

from __future__ import annotations

from datetime import timedelta

from app.config import get_settings
from app.repositories.event_reminder_repository import EventReminderRepository
from app.repositories.hours_ledger_repository import HoursLedgerRepository
from app.services import reminder_service
from app.utils.timefmt import now_utc


async def test_schedule_and_unschedule(fake_redis):
    starts = now_utc() + timedelta(days=2)
    ends = starts + timedelta(hours=3)
    await reminder_service.schedule_for_event(5, starts, ends)
    key = get_settings().reminders_due_key
    members = set(await fake_redis.zrange(key, 0, -1))
    assert members == {"5:t24h", "5:t1h", "5:checkout_nudge"}

    await reminder_service.unschedule(5)
    assert await fake_redis.zcard(key) == 0


async def test_schedule_skips_past_prestart_reminders(fake_redis):
    # event starts in 30 minutes: t24h and t1h are already in the past, only nudge scheduled
    starts = now_utc() + timedelta(minutes=30)
    ends = starts + timedelta(hours=1)
    await reminder_service.schedule_for_event(9, starts, ends)
    members = set(await fake_redis.zrange(get_settings().reminders_due_key, 0, -1))
    assert members == {"9:checkout_nudge"}


async def test_reschedule_replaces_members(fake_redis):
    starts = now_utc() + timedelta(days=2)
    ends = starts + timedelta(hours=3)
    await reminder_service.schedule_for_event(7, starts, ends)
    # reschedule to a new time: old members removed, new ones (still future) present
    new_starts = now_utc() + timedelta(days=5)
    await reminder_service.reschedule(7, new_starts, new_starts + timedelta(hours=2))
    members = set(await fake_redis.zrange(get_settings().reminders_due_key, 0, -1))
    assert members == {"7:t24h", "7:t1h", "7:checkout_nudge"}
    score = await fake_redis.zscore(get_settings().reminders_due_key, "7:t1h")
    assert score == (new_starts - timedelta(hours=1)).timestamp()


async def test_reminder_row_idempotent(session, make_user, make_event):
    user = await make_user()
    event = await make_event()
    repo = EventReminderRepository(session)
    r1 = await repo.ensure_row(event.id, user.id, "t1h")
    r2 = await repo.ensure_row(event.id, user.id, "t1h")
    assert r1.id == r2.id


async def test_auto_ledger_partial_unique_blocks_double_credit(session, make_user, make_event):
    from app.database.models import EventSignup

    user = await make_user()
    event = await make_event()
    signup = EventSignup(event_id=event.id, user_id=user.id, status="checked_out")
    session.add(signup)
    await session.flush()

    repo = HoursLedgerRepository(session)
    assert await repo.upsert_auto_entry(signup.id, user.id, event.id, 60) is True
    assert await repo.upsert_auto_entry(signup.id, user.id, event.id, 999) is False
    assert await repo.total_minutes_for_user(user.id) == 60
