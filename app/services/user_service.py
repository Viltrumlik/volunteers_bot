from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import User, UserRole
from app.repositories.user_repository import UserRepository

if TYPE_CHECKING:
    from aiogram.types import User as TgUser


class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._repo = UserRepository(session)

    def _env_roles(self, telegram_id: int) -> str:
        s = get_settings()
        if telegram_id in s.parsed_super_admin_ids():
            return UserRole.super_admin.value
        if telegram_id in s.parsed_admin_ids():
            return UserRole.admin.value
        return UserRole.user.value

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return await self._repo.get_by_telegram_id(telegram_id)

    async def ensure_env_privileged_stub(self, telegram_user: TgUser) -> User | None:
        tid = telegram_user.id
        s = get_settings()
        if not s.is_env_privileged_user(tid):
            return None
        existing = await self.get_by_telegram_id(tid)
        if existing:
            return await self.ensure_env_roles(existing)
        lc = (getattr(telegram_user, "language_code", None) or "uz").lower()
        lang = "ru" if lc.startswith("ru") else "uz"
        name = (getattr(telegram_user, "full_name", None) or "").strip() or f"Admin {tid}"
        role = self._env_roles(tid)
        u = User(
            telegram_id=tid,
            username=getattr(telegram_user, "username", None),
            full_name=name[:255],
            phone="",
            region_id=None,
            age=None,
            role=role,
            language=lang,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(u)
                await self.session.flush()
        except IntegrityError:
            pass
        out = await self.get_by_telegram_id(tid)
        if out:
            return await self.ensure_env_roles(out)
        return None

    async def touch_activity(self, telegram_id: int, username: str | None = None) -> None:
        await self._repo.touch_activity(telegram_id, username=username)

    async def ensure_env_roles(self, user: User) -> User:
        env_role = self._env_roles(user.telegram_id)
        order = {
            UserRole.user.value: 0,
            UserRole.volunteer.value: 1,
            UserRole.admin.value: 2,
            UserRole.super_admin.value: 3,
        }
        if order.get(env_role, 0) > order.get(user.role, 0):
            user.role = env_role
            await self.session.flush()
        return user

    async def create_user(
        self,
        telegram_id: int,
        full_name: str,
        region_id: int,
        *,
        age: int | None = None,
        language: str = "uz",
        username: str | None = None,
        phone: str | None = None,
        gender: str | None = None,
        bio: str | None = None,
        photo_file_id: str | None = None,
    ) -> User:
        role = self._env_roles(telegram_id)
        u = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            phone=phone if phone is not None else "",
            region_id=region_id,
            age=age,
            gender=gender,
            bio=bio,
            photo_file_id=photo_file_id,
            role=role,
            language=language,
        )
        self.session.add(u)
        await self.session.flush()
        return u

    async def set_language(self, telegram_id: int, lang: str) -> None:
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(language=lang)
        )

    async def count_users(self) -> int:
        return await self._repo.count_users()

    async def count_active_users(self, days: int = 7) -> int:
        return await self._repo.count_active_users(days)

    async def list_users_page(
        self,
        page: int = 1,
        per_page: int = 8,
        query: str | None = None,
    ) -> tuple[list[User], int]:
        return await self._repo.list_users_page(page=page, per_page=per_page, query=query)

    async def set_role(self, telegram_id: int, role: str) -> bool:
        u = await self.get_by_telegram_id(telegram_id)
        if not u:
            return False
        u.role = role
        await self.session.flush()
        return True

    async def all_telegram_ids(self) -> list[int]:
        return await self._repo.all_telegram_ids()
