"""Hours summary + leaderboard (DB aggregation over the append-only ledger)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import User
from app.repositories.hours_ledger_repository import HoursLedgerRepository
from app.utils.timefmt import now_utc


@dataclass(slots=True)
class HoursSummary:
    total_minutes: int
    attended_count: int

    @property
    def hours(self) -> float:
        return round(self.total_minutes / 60, 1)


class HoursService:
    def __init__(self, session: AsyncSession):
        self._ledger = HoursLedgerRepository(session)

    async def my_summary(self, user: User) -> HoursSummary:
        total = await self._ledger.total_minutes_for_user(user.id)
        attended = await self._ledger.attended_count_for_user(user.id)
        return HoursSummary(total_minutes=total, attended_count=attended)

    async def leaderboard(self, *, scope: str = "all") -> list[tuple[int, str, int]]:
        """Return [(telegram_id, full_name, minutes)] top-N. scope 'all' or '30'."""
        since = now_utc() - timedelta(days=30) if scope == "30" else None
        limit = get_settings().leaderboard_size
        return await self._ledger.leaderboard(limit=limit, since=since)
