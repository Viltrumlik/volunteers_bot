import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.monitoring.metrics import record_active_user
from app.services.user_service import UserService

# Keep strong references to fire-and-forget metric tasks so they aren't GC'd mid-flight.
_bg_tasks: set[asyncio.Task[Any]] = set()


class UserContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ):
        session = data.get("session")
        if session is None:
            return await handler(event, data)

        tg_user = None
        if isinstance(event, Message | CallbackQuery):
            tg_user = event.from_user

        if tg_user is not None:
            svc = UserService(session)
            db_user = await svc.get_by_telegram_id(tg_user.id)
            if not db_user:
                db_user = await svc.ensure_env_privileged_stub(tg_user)
            if db_user:
                db_user = await svc.ensure_env_roles(db_user)
                await svc.touch_activity(tg_user.id, username=tg_user.username)
                await session.refresh(db_user)
                task = asyncio.create_task(record_active_user(tg_user.id))
                _bg_tasks.add(task)
                task.add_done_callback(_bg_tasks.discard)
            data["db_user"] = db_user
            data["tg_user"] = tg_user
        else:
            data["db_user"] = None
            data["tg_user"] = None

        return await handler(event, data)
