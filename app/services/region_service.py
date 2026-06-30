from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Region


class RegionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_active_ordered(self) -> list[Region]:
        r = await self.session.execute(
            select(Region).where(Region.is_active.is_(True)).order_by(Region.sort_order, Region.id)
        )
        return list(r.scalars().all())

    async def list_all_ordered(self) -> list[Region]:
        r = await self.session.execute(select(Region).order_by(Region.sort_order, Region.id))
        return list(r.scalars().all())

    async def get(self, region_id: int) -> Region | None:
        r = await self.session.execute(select(Region).where(Region.id == region_id))
        return r.scalar_one_or_none()

    async def create(self, name_uz: str, name_ru: str) -> Region:
        mx = await self.session.scalar(select(func.max(Region.sort_order)))
        nxt = (mx or 0) + 1
        row = Region(
            name_uz=name_uz.strip(), name_ru=name_ru.strip(), is_active=True, sort_order=nxt
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_names(
        self, region_id: int, *, name_uz: str | None = None, name_ru: str | None = None
    ) -> bool:
        reg = await self.get(region_id)
        if not reg:
            return False
        if name_uz is not None:
            reg.name_uz = name_uz.strip()
        if name_ru is not None:
            reg.name_ru = name_ru.strip()
        await self.session.flush()
        return True

    async def set_active(self, region_id: int, active: bool) -> bool:
        r = await self.session.execute(
            update(Region).where(Region.id == region_id).values(is_active=active)
        )
        return r.rowcount > 0

    async def resolve_by_label(self, label: str, language: str) -> Region | None:
        """Match user reply keyboard label to a region."""
        label = (label or "").strip()
        if not label:
            return None
        col = Region.name_ru if language == "ru" else Region.name_uz
        r = await self.session.execute(
            select(Region).where(Region.is_active.is_(True), col == label)
        )
        return r.scalar_one_or_none()
