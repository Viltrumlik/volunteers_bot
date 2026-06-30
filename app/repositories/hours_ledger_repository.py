from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import HoursLedger, LedgerSource, User


class HoursLedgerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_auto_entry(
        self, signup_id: int, user_id: int, event_id: int | None, minutes: int
    ) -> bool:
        """Insert the single auto entry for a signup. Idempotent via the partial
        unique index ``(signup_id) WHERE source='auto'`` — returns False if one exists."""
        existing = await self.session.scalar(
            select(HoursLedger.id).where(
                HoursLedger.signup_id == signup_id,
                HoursLedger.source == LedgerSource.auto.value,
            )
        )
        if existing is not None:
            return False
        entry = HoursLedger(
            user_id=user_id,
            event_id=event_id,
            signup_id=signup_id,
            minutes=minutes,
            source=LedgerSource.auto.value,
        )
        self.session.add(entry)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            self.session.expunge(entry)  # concurrent insert won; drop our pending row
            return False
        return True

    async def add_admin_adjust(
        self,
        *,
        user_id: int,
        event_id: int | None,
        signup_id: int | None,
        minutes: int,
        note: str,
        created_by: int | None,
    ) -> HoursLedger:
        entry = HoursLedger(
            user_id=user_id,
            event_id=event_id,
            signup_id=signup_id,
            minutes=minutes,
            source=LedgerSource.admin_adjust.value,
            note=note,
            created_by=created_by,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def total_minutes_for_user(self, user_id: int) -> int:
        r = await self.session.execute(
            select(func.coalesce(func.sum(HoursLedger.minutes), 0)).where(
                HoursLedger.user_id == user_id
            )
        )
        return int(r.scalar_one())

    async def attended_count_for_user(self, user_id: int) -> int:
        r = await self.session.execute(
            select(func.count())
            .select_from(HoursLedger)
            .where(
                HoursLedger.user_id == user_id,
                HoursLedger.source == LedgerSource.auto.value,
            )
        )
        return int(r.scalar_one())

    async def leaderboard(
        self, *, limit: int = 10, since: datetime | None = None
    ) -> list[tuple[int, str, int]]:
        total = func.sum(HoursLedger.minutes).label("minutes")
        stmt = (
            select(User.telegram_id, User.full_name, total)
            .join(User, User.id == HoursLedger.user_id)
            .group_by(User.telegram_id, User.full_name)
            .having(total > 0)
            .order_by(total.desc())
            .limit(limit)
        )
        if since is not None:
            stmt = stmt.where(HoursLedger.created_at >= since)
        r = await self.session.execute(stmt)
        return [(int(tid), name, int(mins)) for tid, name, mins in r.all()]
