from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.security.rbac import role_grants


class RbacContextMiddleware(BaseMiddleware):
    """Injects `permissions: set[Permission]` for handlers."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db_user = data.get("db_user")
        tg = data.get("tg_user")
        tid = tg.id if tg else None
        if tid is not None:
            data["permissions"] = role_grants(tid, db_user)
        else:
            data["permissions"] = set()
        return await handler(event, data)
