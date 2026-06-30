from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Event, EventStatus


class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, event_id: int) -> Event | None:
        r = await self.session.execute(select(Event).where(Event.id == event_id))
        return r.scalar_one_or_none()

    async def get_for_update(self, event_id: int) -> Event | None:
        """Row-lock the event — the serialization point for capacity decisions."""
        stmt = select(Event).where(Event.id == event_id).with_for_update(of=Event)
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def create(self, **fields: object) -> Event:
        e = Event(**fields)
        self.session.add(e)
        await self.session.flush()
        return e

    async def list_upcoming(
        self, now: datetime, *, page: int = 1, per_page: int = 6, region_id: int | None = None
    ) -> tuple[list[Event], int]:
        conds = [Event.status == EventStatus.open.value, Event.ends_at > now]
        if region_id is not None:
            conds.append(Event.region_id == region_id)
        total = int(
            (
                await self.session.execute(select(func.count()).select_from(Event).where(*conds))
            ).scalar_one()
        )
        pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, pages))
        r = await self.session.execute(
            select(Event)
            .where(*conds)
            .order_by(Event.starts_at)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return list(r.scalars().all()), pages

    async def list_for_admin(self, *, page: int = 1, per_page: int = 6) -> tuple[list[Event], int]:
        total = int(
            (await self.session.execute(select(func.count()).select_from(Event))).scalar_one()
        )
        pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, pages))
        r = await self.session.execute(
            select(Event)
            .order_by(Event.starts_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return list(r.scalars().all()), pages
