from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Event, EventSignup, SignupStatus

# Statuses that occupy a confirmed slot (count toward capacity / appear in roster).
ACTIVE_STATUSES = (
    SignupStatus.registered.value,
    SignupStatus.checked_in.value,
    SignupStatus.checked_out.value,
)


class SignupRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, event_id: int, user_id: int) -> EventSignup | None:
        r = await self.session.execute(
            select(EventSignup).where(
                EventSignup.event_id == event_id, EventSignup.user_id == user_id
            )
        )
        return r.scalar_one_or_none()

    async def get_for_update(self, event_id: int, user_id: int) -> EventSignup | None:
        stmt = (
            select(EventSignup)
            .where(EventSignup.event_id == event_id, EventSignup.user_id == user_id)
            .with_for_update(of=EventSignup)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def get_by_id_for_update(self, signup_id: int) -> EventSignup | None:
        stmt = (
            select(EventSignup)
            .where(EventSignup.id == signup_id)
            .options(selectinload(EventSignup.user), selectinload(EventSignup.event))
            .with_for_update(of=EventSignup)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def create(
        self, event_id: int, user_id: int, status: str, waitlist_pos: int | None = None
    ) -> EventSignup:
        s = EventSignup(
            event_id=event_id, user_id=user_id, status=status, waitlist_pos=waitlist_pos
        )
        self.session.add(s)
        await self.session.flush()
        return s

    async def next_waitlist_pos(self, event_id: int) -> int:
        r = await self.session.execute(
            select(func.coalesce(func.max(EventSignup.waitlist_pos), 0)).where(
                EventSignup.event_id == event_id,
                EventSignup.status == SignupStatus.waitlisted.value,
            )
        )
        return int(r.scalar_one() or 0) + 1

    async def pop_first_waitlisted_for_update(self, event_id: int) -> EventSignup | None:
        stmt = (
            select(EventSignup)
            .where(
                EventSignup.event_id == event_id,
                EventSignup.status == SignupStatus.waitlisted.value,
            )
            .order_by(EventSignup.waitlist_pos)
            .limit(1)
            .options(selectinload(EventSignup.user))
            .with_for_update(of=EventSignup, skip_locked=True)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def list_active_for_event(
        self,
        event_id: int,
        *,
        statuses: tuple[str, ...] = ACTIVE_STATUSES,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[EventSignup]:
        stmt = (
            select(EventSignup)
            .where(EventSignup.event_id == event_id, EventSignup.status.in_(statuses))
            .options(selectinload(EventSignup.user))
            .order_by(EventSignup.id)
            .offset(offset)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        r = await self.session.execute(stmt)
        return list(r.scalars().all())

    async def count_active_for_event(
        self, event_id: int, *, statuses: tuple[str, ...] = ACTIVE_STATUSES
    ) -> int:
        r = await self.session.execute(
            select(func.count())
            .select_from(EventSignup)
            .where(EventSignup.event_id == event_id, EventSignup.status.in_(statuses))
        )
        return int(r.scalar_one())

    async def list_upcoming_for_user(self, user_id: int, now: datetime) -> list[EventSignup]:
        r = await self.session.execute(
            select(EventSignup)
            .join(Event, Event.id == EventSignup.event_id)
            .where(
                EventSignup.user_id == user_id,
                EventSignup.status.in_((*ACTIVE_STATUSES, SignupStatus.waitlisted.value)),
                Event.ends_at > now,
            )
            .options(selectinload(EventSignup.event))
            .order_by(Event.starts_at)
        )
        return list(r.scalars().all())

    async def list_registered_not_checked_in(self, event_id: int) -> list[EventSignup]:
        """No-show sweep candidates: still 'registered', never checked in."""
        r = await self.session.execute(
            select(EventSignup).where(
                EventSignup.event_id == event_id,
                EventSignup.status == SignupStatus.registered.value,
            )
        )
        return list(r.scalars().all())
