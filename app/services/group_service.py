from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LinkedGroup


class GroupService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_chat_id(self, chat_id: int) -> LinkedGroup | None:
        r = await self.session.execute(select(LinkedGroup).where(LinkedGroup.chat_id == chat_id))
        return r.scalar_one_or_none()

    async def upsert_link(
        self, chat_id: int, project_name: str, description: str | None
    ) -> LinkedGroup:
        existing = await self.get_by_chat_id(chat_id)
        if existing:
            existing.project_name = project_name
            existing.description = description
            await self.session.flush()
            return existing
        g = LinkedGroup(chat_id=chat_id, project_name=project_name, description=description)
        self.session.add(g)
        await self.session.flush()
        return g
