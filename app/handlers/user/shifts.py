"""Volunteer shift flows: browse, sign up / waitlist / cancel, check in/out, my shifts."""

from __future__ import annotations

import contextlib
import html
import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from app.database.models import Event, EventStatus, SignupStatus, User
from app.handlers.filters import IsRegistered
from app.handlers.labels import label_set
from app.i18n import t
from app.keyboards.common import main_menu_kb
from app.keyboards.shifts import my_shifts_kb, shift_detail_kb, shifts_list_kb
from app.repositories.signup_repository import SignupRepository
from app.services.attendance_service import AttendanceService
from app.services.event_service import EventService
from app.services.signup_service import SignupService
from app.utils.timefmt import ensure_aware, format_range, format_short, now_utc

logger = logging.getLogger(__name__)
router = Router(name="user_shifts")

_ACTIVE = (
    SignupStatus.registered.value,
    SignupStatus.checked_in.value,
    SignupStatus.checked_out.value,
    SignupStatus.waitlisted.value,
)


def _btn_time(e: Event) -> str:
    return format_short(e.starts_at, e.tz)


def _detail_text(lang: str, e: Event) -> str:
    slots_left = max(0, e.capacity - e.signup_count)
    return t(
        lang,
        "shifts.detail",
        title=html.escape(e.title),
        time=format_range(e.starts_at, e.ends_at, e.tz),
        location=html.escape(e.location or "—"),
        slots_left=slots_left,
        capacity=e.capacity,
        description=html.escape(e.description or ""),
    )


def _flags(e: Event, signup_status: str | None) -> dict[str, bool]:
    now = now_utc()
    starts = ensure_aware(e.starts_at)
    ends = ensure_aware(e.ends_at)
    open_future = e.status == EventStatus.open.value and starts > now
    has_slot = e.signup_count < e.capacity
    active = signup_status in (
        SignupStatus.registered.value,
        SignupStatus.checked_in.value,
        SignupStatus.checked_out.value,
        SignupStatus.waitlisted.value,
    )
    in_checkin_window = (
        starts - timedelta(minutes=e.checkin_opens_min_before)
        <= now
        <= ends + timedelta(minutes=e.checkin_closes_min_after)
    )
    return {
        "can_signup": open_future and not active and has_slot,
        "can_waitlist": open_future and not active and not has_slot,
        "can_cancel": signup_status in _ACTIVE,
        "can_checkin": signup_status == SignupStatus.registered.value and in_checkin_window,
        "can_checkout": signup_status == SignupStatus.checked_in.value,
    }


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    StateFilter(None),
    F.text.in_(label_set("menu.shifts")),
)
async def open_shifts(message: Message, db_user: User, session) -> None:
    await _render_list(message, db_user, session, page=1)


async def _render_list(target, db_user: User, session, *, page: int, edit: bool = False) -> None:
    lang = db_user.language
    events, pages = await EventService(session).list_upcoming(page=page)
    if not events:
        text = t(lang, "shifts.empty")
        if edit:
            await target.edit_text(text)
        else:
            await target.answer(text, reply_markup=main_menu_kb(lang, db_user))
        return
    kb = shifts_list_kb(lang, events, page, pages, fmt=_btn_time)
    text = t(lang, "shifts.browse_title")
    if edit:
        await target.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("sh:"))
async def shifts_callback(
    query: CallbackQuery, db_user: User | None, session, bot, after_commit_tasks
) -> None:
    if not db_user or not query.message:
        await query.answer()
        return
    lang = db_user.language
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "noop":
        await query.answer()
        return
    if action == "close":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.answer()
        await query.message.answer(
            t(lang, "common.menu_hint"), reply_markup=main_menu_kb(lang, db_user)
        )
        return
    if action == "list":
        page = _int(parts, 2, 1)
        await _render_list(query.message, db_user, session, page=page, edit=True)
        await query.answer()
        return
    if action == "my":
        signups = await SignupService(session).list_my_upcoming(db_user)
        if not signups:
            await query.answer(t(lang, "shifts.my_shifts_empty"), show_alert=True)
            return
        await query.message.edit_text(
            t(lang, "shifts.my_shifts_title"),
            reply_markup=my_shifts_kb(lang, signups, fmt=_btn_time),
        )
        await query.answer()
        return

    event_id = _int(parts, 2, 0)
    if not event_id:
        await query.answer()
        return

    if action == "v":
        await _show_detail(query, db_user, session, event_id)
        return
    if action in ("j", "w"):
        row, err = await SignupService(session).sign_up(db_user, event_id)
        if err:
            await query.answer(t(lang, err), show_alert=True)
            return
        key = (
            "shifts.signed_up"
            if row.status == SignupStatus.registered.value
            else "shifts.waitlisted"
        )
        await query.answer(t(lang, key, pos=row.waitlist_pos or 0), show_alert=True)
        await _show_detail(query, db_user, session, event_id)
        return
    if action == "c":
        ok, err, promo = await SignupService(session).cancel(db_user, event_id)
        if not ok:
            await query.answer(t(lang, err), show_alert=True)
            return
        if promo:
            after_commit_tasks.append(_notify_promoted(bot, promo))
        await query.answer(t(lang, "shifts.cancelled_ok"), show_alert=True)
        await _show_detail(query, db_user, session, event_id)
        return
    if action == "ci":
        ok, err = await AttendanceService(session).check_in(db_user, event_id)
        await query.answer(t(lang, "shifts.checked_in_ok" if ok else err), show_alert=True)
        await _show_detail(query, db_user, session, event_id)
        return
    if action == "co":
        ok, err, mins = await AttendanceService(session).check_out(db_user, event_id)
        await query.answer(
            t(lang, "shifts.checkout_ok", minutes=mins) if ok else t(lang, err), show_alert=True
        )
        await _show_detail(query, db_user, session, event_id)
        return
    await query.answer()


async def _show_detail(query: CallbackQuery, db_user: User, session, event_id: int) -> None:
    lang = db_user.language
    event = await EventService(session).get(event_id)
    if not event:
        await query.answer(t(lang, "shifts.not_found"), show_alert=True)
        return
    signup = await SignupRepository(session).get(event_id, db_user.id)
    flags = _flags(event, signup.status if signup else None)
    with contextlib.suppress(Exception):  # message unchanged / not editable
        await query.message.edit_text(
            _detail_text(lang, event),
            reply_markup=shift_detail_kb(lang, event_id, **flags),
            parse_mode=ParseMode.HTML,
        )


def _notify_promoted(bot, promo):
    async def _job() -> None:
        try:
            await bot.send_message(
                promo.telegram_id,
                t(promo.language, "shifts.promoted_notify", title=promo.event_title),
            )
        except Exception as exc:  # user blocked the bot, etc.
            logger.info("promote notify failed: %s", exc)

    return _job()


def _int(parts: list[str], idx: int, default: int) -> int:
    try:
        return int(parts[idx])
    except (IndexError, ValueError):
        return default
