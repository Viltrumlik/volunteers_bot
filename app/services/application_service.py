from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Application, ApplicationStatus, User, UserRole
from app.repositories.application_repository import ApplicationRepository
from app.repositories.project_repository import ProjectRepository


class ApplicationService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = ApplicationRepository(session)
        self._projects = ProjectRepository(session)

    async def apply(self, user: User, project_id: int) -> tuple[Application | None, str]:
        """Idempotent apply under row lock; project must exist and be active."""
        project = await self._projects.get(project_id)
        if not project or not project.is_active:
            return None, "projects.inactive"

        existing = await self._repo.get_for_user_project_for_update(user.id, project_id)
        if not existing:
            return await self._repo.create_pending(user.id, project_id), ""
        if existing.status == ApplicationStatus.pending.value:
            return None, "projects.apply_pending"
        if existing.status == ApplicationStatus.approved.value:
            return None, "projects.apply_already"
        if existing.status == ApplicationStatus.rejected.value:
            existing.status = ApplicationStatus.pending.value
            existing.note = None
            await self._session.flush()
            return existing, ""
        return None, "projects.apply_pending"

    async def approve_or_reject(self, application_id: int, *, approve: bool) -> tuple[bool, str]:
        """
        Single decision under row lock. Prevents double-approve/reject.
        Promotes user to volunteer on approve if currently user.
        """
        app = await self._repo.get_by_id_for_update(application_id)
        if not app:
            return False, "admin_apps.not_found"
        if app.status != ApplicationStatus.pending.value:
            return False, "admin_apps.not_pending"
        app.status = (
            ApplicationStatus.approved.value if approve else ApplicationStatus.rejected.value
        )
        u = app.user
        if approve and u and u.role == UserRole.user.value:
            u.role = UserRole.volunteer.value
        await self._session.flush()
        return True, ""

    async def list_pending(self) -> list[Application]:
        return await self._repo.list_pending_with_users()

    async def get(self, application_id: int) -> Application | None:
        return await self._repo.get(application_id)

    async def set_status(self, application: Application, status: str) -> None:
        application.status = status
        await self._session.flush()

    async def list_for_profile(self, user_id: int) -> list[Application]:
        return await self._repo.list_approved_for_user(user_id)
