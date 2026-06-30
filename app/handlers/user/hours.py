"""Volunteer hours summary + leaderboard."""

from __future__ import annotations

import contextlib
import html

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from app.database.models import User
from app.handlers.filters import IsRegistered
from app.handlers.labels import label_set
from app.i18n import t
from app.keyboards.common import main_menu_kb
from app.keyboards.shifts import hours_kb
from app.services.hours_service import HoursService

router = Router(name="user_hours")


def _summary_text(lang: str, summary) -> str:
    if summary.attended_count == 0 and summary.total_minutes == 0:
        return t(lang, "hours.my_empty")
    return (
        t(lang, "hours.my_title")
        + "\n"
        + t(lang, "hours.my_total", hours=summary.hours, minutes=summary.total_minutes)
        + "\n"
        + t(lang, "hours.my_shifts_count", count=summary.attended_count)
    )


def _leaderboard_text(lang: str, scope: str, rows: list[tuple[int, str, int]]) -> str:
    title = t(
        lang, "hours.leaderboard_title_30" if scope == "30" else "hours.leaderboard_title_all"
    )
    if not rows:
        return title + "\n" + t(lang, "hours.leaderboard_empty")
    lines = [title]
    for i, (_tid, name, minutes) in enumerate(rows, start=1):
        lines.append(
            t(
                lang,
                "hours.leaderboard_row",
                rank=i,
                name=html.escape(name),
                hours=round(minutes / 60, 1),
            )
        )
    return "\n".join(lines)


@router.message(
    F.chat.type == "private", IsRegistered(), StateFilter(None), F.text.in_(label_set("menu.hours"))
)
async def open_hours(message: Message, db_user: User, session) -> None:
    lang = db_user.language
    summary = await HoursService(session).my_summary(db_user)
    await message.answer(_summary_text(lang, summary), reply_markup=hours_kb(lang))


@router.callback_query(F.data.startswith("hr:"))
async def hours_callback(query: CallbackQuery, db_user: User | None, session) -> None:
    if not db_user or not query.message:
        await query.answer()
        return
    lang = db_user.language
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "close":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.answer()
        await query.message.answer(
            t(lang, "common.menu_hint"), reply_markup=main_menu_kb(lang, db_user)
        )
        return
    if action == "me":
        summary = await HoursService(session).my_summary(db_user)
        await _safe_edit(query, _summary_text(lang, summary), lang)
        await query.answer()
        return
    if action == "lb":
        scope = parts[2] if len(parts) > 2 else "all"
        rows = await HoursService(session).leaderboard(scope=scope)
        await _safe_edit(query, _leaderboard_text(lang, scope, rows), lang)
        await query.answer()
        return
    await query.answer()


async def _safe_edit(query: CallbackQuery, text: str, lang: str) -> None:
    with contextlib.suppress(Exception):
        await query.message.edit_text(text, reply_markup=hours_kb(lang))
