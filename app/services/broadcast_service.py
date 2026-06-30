from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import get_settings
from app.utils.urls import is_safe_button_url

logger = logging.getLogger(__name__)


def parse_inline_buttons(raw: str | None) -> InlineKeyboardMarkup | None:
    if not raw or not raw.strip():
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        text, url = line.split("|", 1)
        text, url = text.strip(), url.strip()
        # Only https:// and tg:// to non-internal hosts (defence-in-depth vs SSRF-style links).
        if text and is_safe_button_url(url):
            rows.append([InlineKeyboardButton(text=text, url=url)])
        elif text and url:
            logger.warning("Broadcast button URL rejected: %.60s", url)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


class BroadcastService:
    @staticmethod
    async def send_to_users(
        bot: Bot,
        telegram_ids: list[int],
        *,
        text: str | None = None,
        photo_file_id: str | None = None,
        photo_path: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> tuple[int, int]:
        settings = get_settings()
        batch = settings.broadcast_batch_size
        delay = settings.broadcast_delay_sec
        ok, fail = 0, 0
        for i in range(0, len(telegram_ids), batch):
            chunk = telegram_ids[i : i + batch]
            for uid in chunk:
                try:
                    if photo_file_id:
                        await bot.send_photo(
                            uid,
                            photo_file_id,
                            caption=text,
                            reply_markup=reply_markup,
                        )
                    elif photo_path:
                        await bot.send_photo(
                            uid,
                            FSInputFile(photo_path),
                            caption=text,
                            reply_markup=reply_markup,
                        )
                    elif text:
                        await bot.send_message(uid, text, reply_markup=reply_markup)
                    ok += 1
                except Exception as e:
                    logger.warning("Broadcast fail user %s: %s", uid, e)
                    fail += 1
            await asyncio.sleep(delay)
        return ok, fail
