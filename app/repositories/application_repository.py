from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Application, ApplicationStatus


class ApplicationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_for_user_project(self, user_id: int, project_id: int) -> Application | None:
        r = await self.session.execute(
            select(Application).where(
                Application.user_id == user_id, Application.project_id == project_id
            )
        )
        return r.scalar_one_or_none()

    async def get_for_user_project_for_update(
        self, user_id: int, project_id: int
    ) -> Application | None:
        stmt = (
            select(Application)
            .where(Application.user_id == user_id, Application.project_id == project_id)
            .with_for_update(of=Application)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def get_by_id_for_update(self, application_id: int) -> Application | None:
        stmt = (
            select(Application)
            .where(Application.id == application_id)
            .options(selectinload(Application.user), selectinload(Application.project))
            .with_for_update(of=Application)
        )
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def create_pending(self, user_id: int, project_id: int) -> Application:
        a = Application(
            user_id=user_id,
            project_id=project_id,
            status=ApplicationStatus.pending.value,
        )
        self.session.add(a)
        await self.session.flush()
        return a

    async def list_pending_with_users(self) -> list[Application]:
        r = await self.session.execute(
            select(Application)
            .where(Application.status == ApplicationStatus.pending.value)
            .options(selectinload(Application.user), selectinload(Application.project))
            .order_by(Application.created_at)
        )
        return list(r.scalars().all())

    async def get(self, application_id: int) -> Application | None:
        r = await self.session.execute(
            select(Application)
            .where(Application.id == application_id)
            .options(selectinload(Application.user), selectinload(Application.project))
        )
        return r.scalar_one_or_none()

    async def list_for_user(self, user_id: int) -> list[Application]:
        r = await self.session.execute(
            select(Application)
            .where(Application.user_id == user_id)
            .options(selectinload(Application.project))
            .order_by(Application.created_at.desc())
        )
        return list(r.scalars().all())

    async def list_approved_for_user(self, user_id: int) -> list[Application]:
        r = await self.session.execute(
            select(Application)
            .where(
                Application.user_id == user_id,
                Application.status == ApplicationStatus.approved.value,
            )
            .options(selectinload(Application.project))
            .order_by(Application.updated_at.desc())
        )
        return list(r.scalars().all())
