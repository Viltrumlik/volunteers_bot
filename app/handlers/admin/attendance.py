"""Admin attendance: roster, mark check-in/out/no-show, manual hours adjustment (FSM)."""

from __future__ import annotations

import contextlib
import html
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.database.models import User
from app.handlers.filters import IsAdmin, IsRegistered
from app.i18n import t
from app.keyboards.common import main_menu_kb
from app.keyboards.shifts import roster_kb, signup_actions_kb
from app.services import audit_service
from app.services.attendance_service import AttendanceService
from app.services.event_service import EventService
from app.states.forms import AdminHoursAdjustStates

logger = logging.getLogger(__name__)
router = Router(name="admin_attendance")


@router.callback_query(F.data.startswith("aa:"), IsAdmin())
async def attendance_callback(
    query: CallbackQuery, state: FSMContext, db_user: User, session
) -> None:
    if not query.message:
        await query.answer()
        return
    lang = db_user.language
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "v":  # roster: aa:v:<event_id>:<page>
        event_id, page = _int(parts, 2, 0), _int(parts, 3, 1)
        await _render_roster(query, db_user, session, event_id, page)
        return
    if action == "s":  # signup actions: aa:s:<signup_id>:<event_id>
        sid, eid = _int(parts, 2, 0), _int(parts, 3, 0)
        with contextlib.suppress(Exception):
            await query.message.edit_reply_markup(reply_markup=signup_actions_kb(lang, sid, eid))
        await query.answer()
        return
    if action == "mark":  # aa:mark:<signup_id>:<state>:<event_id>
        sid, st, eid = _int(parts, 2, 0), parts[3] if len(parts) > 3 else "", _int(parts, 4, 0)
        signup, err = await AttendanceService(session).admin_mark(sid, st)
        if err:
            await query.answer(t(lang, err), show_alert=True)
            return
        await audit_service.record(
            session,
            actor_telegram_id=query.from_user.id,
            action="attendance_mark",
            target_type="signup",
            target_id=sid,
            summary=st,
        )
        await query.answer(t(lang, "admin_attendance.mark_done", status=st), show_alert=True)
        await _render_roster(query, db_user, session, eid, 1)
        return
    if action == "adj":  # aa:adj:<signup_id>:<event_id>
        sid, eid = _int(parts, 2, 0), _int(parts, 3, 0)
        await state.set_state(AdminHoursAdjustStates.minutes)
        await state.update_data(adj_signup_id=sid, adj_event_id=eid)
        await query.message.answer(t(lang, "admin_attendance.adjust_minutes_prompt"))
        await query.answer()
        return
    await query.answer()


async def _render_roster(
    query: CallbackQuery, db_user: User, session, event_id: int, page: int
) -> None:
    lang = db_user.language
    event = await EventService(session).get(event_id)
    if not event:
        await query.answer(t(lang, "shifts.not_found"), show_alert=True)
        return
    signups, pages = await AttendanceService(session).roster(event_id, page=page)
    title = t(lang, "admin_attendance.roster_title", title=html.escape(event.title))
    if not signups:
        title += "\n" + t(lang, "admin_attendance.roster_empty")
    with contextlib.suppress(Exception):
        await query.message.edit_text(
            title, reply_markup=roster_kb(lang, signups, event_id, page, pages)
        )
    await query.answer()


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    IsAdmin(),
    StateFilter(AdminHoursAdjustStates.minutes),
    F.text,
)
async def adjust_minutes(message: Message, state: FSMContext, db_user: User) -> None:
    lang = db_user.language
    raw = message.text.strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(t(lang, "admin_attendance.bad_minutes"))
        return
    await state.update_data(adj_minutes=int(raw))
    await state.set_state(AdminHoursAdjustStates.note)
    await message.answer(t(lang, "admin_attendance.adjust_note_prompt"))


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    IsAdmin(),
    StateFilter(AdminHoursAdjustStates.note),
    F.text,
)
async def adjust_note(message: Message, state: FSMContext, db_user: User, session) -> None:
    lang = db_user.language
    note = (message.text or "").strip()
    data = await state.get_data()
    entry, err = await AttendanceService(session).admin_adjust_hours(
        admin=db_user,
        signup_id=int(data["adj_signup_id"]),
        minutes=int(data["adj_minutes"]),
        note=note,
    )
    if err or entry is None:
        await message.answer(t(lang, err or "errors.generic"))
        return
    await audit_service.record(
        session,
        actor_telegram_id=db_user.telegram_id,
        action="hours_adjust",
        target_type="signup",
        target_id=data["adj_signup_id"],
        summary=f"{data['adj_minutes']}min",
    )
    await state.clear()
    await message.answer(
        t(lang, "admin_attendance.adjusted", minutes=data["adj_minutes"]),
        reply_markup=main_menu_kb(lang, db_user),
    )


def _int(parts: list[str], idx: int, default: int) -> int:
    try:
        return int(parts[idx])
    except (IndexError, ValueError):
        return default
