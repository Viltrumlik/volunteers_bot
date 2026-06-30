"""Resolve Telegram sender from middleware injection or the message."""

from __future__ import annotations

from aiogram.types import Message
from aiogram.types import User as TgUser


def effective_telegram_user(message: Message, injected: TgUser | None) -> TgUser | None:
    return injected if injected is not None else message.from_user
