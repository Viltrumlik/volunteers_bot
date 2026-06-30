"""
Build Telegram keyboards from database rows.

Selectable business options (regions, FAQ categories, …) never come from
hardcoded Python literals — only from DB + i18n labels for non-data keys.
"""

from __future__ import annotations

from typing import Literal

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import FAQ, FAQCategory, Region
from app.services.faq_category_service import FAQCategoryService
from app.services.region_service import RegionService

DynamicReplyKind = Literal["regions"]
DynamicInlineKind = Literal["faq_categories", "faqs_in_category"]


def _label_for_lang(obj: Region | FAQCategory, language: str) -> str:
    if language == "ru":
        return (obj.name_ru or obj.name_uz)[:256]
    return (obj.name_uz or obj.name_ru)[:256]


async def get_dynamic_reply_keyboard(
    session: AsyncSession,
    *,
    kind: DynamicReplyKind,
    language: str,
    per_row: int = 2,
) -> ReplyKeyboardMarkup | None:
    """
    Build a ReplyKeyboardMarkup from DB rows.

    ``kind`` maps to a logical list (not raw SQL table names) for type-safety.
    """
    if kind == "regions":
        rows_data = await RegionService(session).list_active_ordered()
        if not rows_data:
            return None
        buttons: list[list[KeyboardButton]] = []
        row: list[KeyboardButton] = []
        for r in rows_data:
            row.append(KeyboardButton(text=_label_for_lang(r, language)))
            if len(row) >= per_row:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    return None


async def get_dynamic_inline_keyboard(
    session: AsyncSession,
    *,
    kind: DynamicInlineKind,
    language: str,
    callback_prefix: str,
    category_id: int | None = None,
) -> InlineKeyboardMarkup | None:
    """Build InlineKeyboardMarkup from DB (categories or FAQs in a category)."""
    if kind == "faq_categories":
        cats = await FAQCategoryService(session).list_active_ordered()
        if not cats:
            return None
        lines: list[list[InlineKeyboardButton]] = []
        for c in cats:
            lines.append(
                [
                    InlineKeyboardButton(
                        text=_label_for_lang(c, language)[:64],
                        callback_data=f"{callback_prefix}:c:{c.id}",
                    )
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=lines)

    if kind == "faqs_in_category":
        if category_id is None:
            return None
        from app.services.faq_service import FAQService

        faqs = await FAQService(session).list_by_category_ordered(category_id)
        if not faqs:
            return None
        lines = _faq_rows(faqs, language, callback_prefix)
        return InlineKeyboardMarkup(inline_keyboard=lines)

    return None


def _faq_rows(faqs: list[FAQ], language: str, prefix: str) -> list[list[InlineKeyboardButton]]:
    lines: list[list[InlineKeyboardButton]] = []
    for f in faqs:
        title = f.question_ru if language == "ru" and f.question_ru else f.question_uz
        lines.append([InlineKeyboardButton(text=title[:64], callback_data=f"{prefix}:q:{f.id}")])
    return lines


# Backwards-compatible alias requested in spec
_TABLE_TO_REPLY: dict[str, DynamicReplyKind] = {"regions": "regions"}


async def get_dynamic_keyboard(
    session: AsyncSession,
    table_name: str,
    language: str,
    *,
    per_row: int = 2,
) -> ReplyKeyboardMarkup | None:
    """Map a logical table name to a reply keyboard (regions only for now)."""
    kind = _TABLE_TO_REPLY.get(table_name.lower())
    if not kind:
        return None
    return await get_dynamic_reply_keyboard(session, kind=kind, language=language, per_row=per_row)
