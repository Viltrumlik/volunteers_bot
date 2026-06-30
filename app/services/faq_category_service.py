from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import FAQCategory


class FAQCategoryService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_active_ordered(self) -> list[FAQCategory]:
        r = await self.session.execute(
            select(FAQCategory)
            .where(FAQCategory.is_active.is_(True))
            .order_by(FAQCategory.sort_order, FAQCategory.id)
        )
        return list(r.scalars().all())

    async def list_all_ordered(self) -> list[FAQCategory]:
        r = await self.session.execute(
            select(FAQCategory).order_by(FAQCategory.sort_order, FAQCategory.id)
        )
        return list(r.scalars().all())

    async def get(self, category_id: int) -> FAQCategory | None:
        r = await self.session.execute(select(FAQCategory).where(FAQCategory.id == category_id))
        return r.scalar_one_or_none()

    async def create(self, name_uz: str, name_ru: str) -> FAQCategory:
        mx = await self.session.scalar(select(func.max(FAQCategory.sort_order)))
        nxt = (mx or 0) + 1
        row = FAQCategory(
            name_uz=name_uz.strip(), name_ru=name_ru.strip(), is_active=True, sort_order=nxt
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_names(
        self, category_id: int, *, name_uz: str | None = None, name_ru: str | None = None
    ) -> bool:
        c = await self.get(category_id)
        if not c:
            return False
        if name_uz is not None:
            c.name_uz = name_uz.strip()
        if name_ru is not None:
            c.name_ru = name_ru.strip()
        await self.session.flush()
        return True

    async def set_active(self, category_id: int, active: bool) -> bool:
        r = await self.session.execute(
            update(FAQCategory).where(FAQCategory.id == category_id).values(is_active=active)
        )
        return r.rowcount > 0
