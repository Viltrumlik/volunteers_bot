from typing import Any

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import get_settings
from app.database.models import User, UserRole
from app.security.rbac import Permission, has_permission


def may_use_admin_tools(telegram_id: int, db_user: User | None) -> bool:
    """DB admin/super_admin or any id listed in ADMIN_IDS / SUPER_ADMIN_IDS."""
    if get_settings().is_env_privileged_user(telegram_id):
        return True
    return bool(db_user and db_user.role in (UserRole.admin.value, UserRole.super_admin.value))


def _telegram_id_from_event(event: TelegramObject) -> int | None:
    if isinstance(event, Message) and event.from_user:
        return event.from_user.id
    if isinstance(event, CallbackQuery) and event.from_user:
        return event.from_user.id
    return None


class IsRegistered(Filter):
    async def __call__(self, _: Any, db_user: User | None = None) -> bool:
        return db_user is not None


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, db_user: User | None = None) -> bool:
        tid = _telegram_id_from_event(event)
        s = get_settings()
        if tid is not None and s.is_env_privileged_user(tid):
            return True
        if not db_user:
            return False
        return db_user.role in (UserRole.admin.value, UserRole.super_admin.value)


class IsSuperAdmin(Filter):
    async def __call__(self, event: TelegramObject, db_user: User | None = None) -> bool:
        tid = _telegram_id_from_event(event)
        s = get_settings()
        if tid is not None and tid in s.parsed_super_admin_ids():
            return True
        if not db_user:
            return False
        return db_user.role == UserRole.super_admin.value


class InAdminGroup(Filter):
    async def __call__(self, message: Message) -> bool:
        s = get_settings()
        return message.chat is not None and message.chat.id == s.admin_group_id


class RequiresPermission(Filter):
    """RBAC: Permission enum (see app.security.rbac)."""

    def __init__(self, permission: Permission) -> None:
        self.permission = permission

    async def __call__(self, event: TelegramObject, db_user: User | None = None) -> bool:
        tid = _telegram_id_from_event(event)
        if tid is None:
            return False
        return has_permission(tid, db_user, self.permission)
