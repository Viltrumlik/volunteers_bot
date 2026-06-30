from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_active(self) -> list[Project]:
        r = await self.session.execute(
            select(Project)
            .where(Project.is_active.is_(True))
            .order_by(Project.sort_order, Project.id)
        )
        return list(r.scalars().all())

    async def get(self, project_id: int) -> Project | None:
        r = await self.session.execute(select(Project).where(Project.id == project_id))
        return r.scalar_one_or_none()

    async def create(self, title: str, description: str, *, sort_order: int = 0) -> Project:
        p = Project(title=title, description=description, is_active=True, sort_order=sort_order)
        self.session.add(p)
        await self.session.flush()
        return p
