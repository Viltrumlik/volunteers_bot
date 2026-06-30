from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import get_settings
from app.i18n import t
from app.infrastructure import rate_limiter


class RateLimitMiddleware(BaseMiddleware):
    """Per-user sliding-window limit (atomic Lua script in Redis; private chats only)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        uid: int | None = None
        if isinstance(event, Message) and event.from_user:
            if event.chat.type != "private":
                return await handler(event, data)
            uid = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            msg = event.message
            if msg is None or msg.chat.type != "private":
                return await handler(event, data)
            uid = event.from_user.id
        if uid is None:
            return await handler(event, data)

        settings = get_settings()
        allowed = await rate_limiter.allow(
            uid,
            limit=settings.rate_limit_messages,
            window_sec=float(settings.rate_limit_window_sec),
        )
        if not allowed:
            lang = getattr(data.get("db_user"), "language", None) or "uz"
            if isinstance(event, Message):
                await event.answer(t(lang, "errors.rate_limited"))
            elif isinstance(event, CallbackQuery):
                await event.answer(t(lang, "errors.rate_limited"), show_alert=True)
            return None
        return await handler(event, data)
