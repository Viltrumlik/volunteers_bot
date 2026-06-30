from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import EventReminder, ReminderStatus


class EventReminderRepository:
    """Idempotent per-(event, user, kind) reminder rows — the at-most-once guarantee."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_row(self, event_id: int, user_id: int, kind: str) -> EventReminder:
        row = await self._get(event_id, user_id, kind)
        if row:
            return row
        row = EventReminder(
            event_id=event_id,
            user_id=user_id,
            kind=kind,
            status=ReminderStatus.pending.value,
        )
        self.session.add(row)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            existing = await self._get(event_id, user_id, kind)
            if existing:
                return existing
            raise
        return row

    async def _get(self, event_id: int, user_id: int, kind: str) -> EventReminder | None:
        r = await self.session.execute(
            select(EventReminder).where(
                EventReminder.event_id == event_id,
                EventReminder.user_id == user_id,
                EventReminder.kind == kind,
            )
        )
        return r.scalar_one_or_none()

    async def _set(self, reminder_id: int, **vals: object) -> None:
        vals["updated_at"] = datetime.now(UTC)
        await self.session.execute(
            update(EventReminder).where(EventReminder.id == reminder_id).values(**vals)
        )

    async def mark_sent(self, reminder_id: int) -> None:
        await self._set(reminder_id, status=ReminderStatus.sent.value, sent_at=datetime.now(UTC))

    async def mark_skipped(self, reminder_id: int) -> None:
        await self._set(reminder_id, status=ReminderStatus.skipped.value)

    async def mark_failed(self, reminder_id: int, error: str, *, attempts: int) -> None:
        await self._set(
            reminder_id,
            status=ReminderStatus.failed.value,
            last_error=error[:4000],
            attempts=attempts,
        )

    async def mark_dead_letter(self, reminder_id: int, error: str, *, attempts: int) -> None:
        await self._set(
            reminder_id,
            status=ReminderStatus.dead_letter.value,
            last_error=error[:4000],
            attempts=attempts,
        )
