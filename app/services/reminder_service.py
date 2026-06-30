"""Shift reminders: a Redis ZSET due-queue + idempotent ``event_reminders`` rows.

Scheduling: ``ZADD reminders:due <send-at-epoch> "<event_id>:<kind>"`` on create,
re-add on time-edit, remove on cancel. The member is per-event (not per-user) so a
late signup is automatically covered when the reminder fires.

Delivery: a single worker tick (guarded by a fail-closed fence lock) pops everything
due and fans out per recipient. ``EventReminderRepository.ensure_row`` + a UNIQUE
(event, user, kind) make each reminder send at most once, even across worker restarts —
the lock is an optimization; the UNIQUE row is the real fence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta

from aiogram import Bot

from app.config import get_settings
from app.database.models import ReminderKind, SignupStatus
from app.database.session import get_session_factory
from app.i18n import t
from app.infrastructure.redis_lock import redis_lock_strict
from app.monitoring.metrics import incr
from app.repositories.event_reminder_repository import EventReminderRepository
from app.repositories.event_repository import EventRepository
from app.repositories.signup_repository import SignupRepository
from app.services.attendance_service import AttendanceService
from app.services.news_dispatch_service import _send_with_retries
from app.utils.timefmt import ensure_aware, format_local

logger = logging.getLogger(__name__)

_ALL_KINDS = (ReminderKind.t24h.value, ReminderKind.t1h.value, ReminderKind.checkout_nudge.value)

# Which signup statuses receive each reminder kind.
_RECIPIENTS: dict[str, tuple[str, ...]] = {
    ReminderKind.t24h.value: (SignupStatus.registered.value, SignupStatus.checked_in.value),
    ReminderKind.t1h.value: (SignupStatus.registered.value, SignupStatus.checked_in.value),
    ReminderKind.checkout_nudge.value: (SignupStatus.checked_in.value,),
}


def _member(event_id: int, kind: str) -> str:
    return f"{event_id}:{kind}"


def _send_at(kind: str, starts_at: datetime, ends_at: datetime) -> datetime:
    starts_at, ends_at = ensure_aware(starts_at), ensure_aware(ends_at)
    if kind == ReminderKind.t24h.value:
        return starts_at - timedelta(hours=24)
    if kind == ReminderKind.t1h.value:
        return starts_at - timedelta(hours=1)
    return ends_at + timedelta(minutes=get_settings().checkout_nudge_delay_min)


# ---------------------------------------------------------------------------
# Scheduler (called from handlers' after_commit_tasks)
# ---------------------------------------------------------------------------
async def schedule_for_event(event_id: int, starts_at: datetime, ends_at: datetime) -> None:
    from app.infrastructure.redis_connection import get_redis

    r = await get_redis()
    if r is None:
        return
    key = get_settings().reminders_due_key
    now = time.time()
    mapping: dict[str, float] = {}
    for kind in _ALL_KINDS:
        epoch = _send_at(kind, starts_at, ends_at).timestamp()
        # Skip pre-start reminders whose moment already passed; always keep checkout nudge.
        if kind != ReminderKind.checkout_nudge.value and epoch <= now:
            continue
        mapping[_member(event_id, kind)] = epoch
    if mapping:
        await r.zadd(key, mapping)  # type: ignore[arg-type]


async def reschedule(event_id: int, starts_at: datetime, ends_at: datetime) -> None:
    await unschedule(event_id)
    await schedule_for_event(event_id, starts_at, ends_at)


async def unschedule(event_id: int) -> None:
    from app.infrastructure.redis_connection import get_redis

    r = await get_redis()
    if r is None:
        return
    key = get_settings().reminders_due_key
    await r.zrem(key, *[_member(event_id, k) for k in _ALL_KINDS])


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
async def _push_dlq(payload: dict[str, object]) -> None:
    from app.infrastructure.redis_connection import get_redis

    r = await get_redis()
    if r is None:
        return
    await r.rpush(get_settings().reminders_dlq_key, json.dumps(payload, ensure_ascii=False))


async def process_due_reminder(bot: Bot, event_id: int, kind: str) -> None:
    settings = get_settings()
    factory = get_session_factory()

    async with factory() as session:
        event = await EventRepository(session).get(event_id)
        if not event or event.status == "cancelled":
            return
        statuses = _RECIPIENTS.get(kind, ())
        signups = await SignupRepository(session).list_active_for_event(event_id, statuses=statuses)
        recipients = [(s.user_id, s.user.telegram_id, s.user.language) for s in signups]
        title = event.title
        when = format_local(event.starts_at, event.tz)

    mps = max(1.0, min(25.0, settings.news_messages_per_sec))
    min_interval = 1.0 / mps

    for user_id, tid, lang in recipients:
        t0 = time.monotonic()
        async with factory() as session:
            rrepo = EventReminderRepository(session)
            row = await rrepo.ensure_row(event_id, user_id, kind)
            rid = row.id
            already = row.status == "sent"
            await session.commit()
        if already:
            continue

        text = t(lang, f"reminders.{kind}", title=title, time=when)
        ok, err, att = await _send_with_retries(
            bot,
            tid,
            text=text,
            photo_file_id=None,
            markup=None,
            max_retries=settings.news_max_retries,
            base_delay=settings.news_retry_base_delay_sec,
        )
        async with factory() as session:
            rrepo = EventReminderRepository(session)
            if ok:
                await rrepo.mark_sent(rid)
                await incr("reminders_sent")
            else:
                await rrepo.mark_dead_letter(rid, err or "unknown", attempts=att)
                await incr("reminders_failed")
                await _push_dlq(
                    {"event_id": event_id, "user_telegram_id": tid, "kind": kind, "error": err}
                )
            await session.commit()

        elapsed = time.monotonic() - t0
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)

    if kind == ReminderKind.checkout_nudge.value:
        async with factory() as session:
            n = await AttendanceService(session).sweep_no_shows(event_id)
            await session.commit()
            if n:
                logger.info("no-show sweep event=%s flipped=%s", event_id, n)


async def process_due_reminder_safe(bot: Bot, event_id: int, kind: str) -> None:
    try:
        await process_due_reminder(bot, event_id, kind)
    except Exception as exc:  # one bad reminder must not stall the tick
        logger.exception("reminder %s/%s failed: %s", event_id, kind, exc)
        await incr("reminders_job_fail")


async def reminders_worker_loop(bot: Bot) -> None:
    from app.infrastructure.redis_connection import get_redis

    settings = get_settings()
    r = await get_redis()
    if r is None:
        logger.error("Reminders worker: Redis required")
        return
    key = settings.reminders_due_key
    poll = settings.reminders_poll_interval_sec
    logger.info("Reminders worker polling %s every %ss", key, poll)
    while True:
        try:
            async with redis_lock_strict(
                "volunteers_bot:lock:reminders:tick", ttl_sec=poll + 10
            ) as got:
                if got:
                    now = time.time()
                    due = await r.zrangebyscore(key, 0, now)
                    for member in due:
                        try:
                            event_id_s, kind = member.split(":", 1)
                            await process_due_reminder_safe(bot, int(event_id_s), kind)
                        finally:
                            await r.zrem(key, member)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Reminders tick error: %s", exc)
        await asyncio.sleep(poll)
