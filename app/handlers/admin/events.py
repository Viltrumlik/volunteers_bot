"""Admin shift management: create (FSM), list, detail, close, cancel."""

from __future__ import annotations

import contextlib
import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import get_settings
from app.database.models import Event, User
from app.handlers.filters import IsAdmin, IsRegistered
from app.handlers.labels import label_set
from app.i18n import t
from app.keyboards.common import main_menu_kb
from app.keyboards.shifts import (
    admin_event_cancel_confirm_kb,
    admin_event_detail_kb,
    admin_event_edit_fields_kb,
    admin_events_list_kb,
)
from app.services import audit_service, reminder_service
from app.services.event_service import EventService
from app.states.forms import AdminEventEditStates, AdminEventStates
from app.utils.timefmt import format_range, format_short, parse_local_to_utc, valid_tz

logger = logging.getLogger(__name__)
router = Router(name="admin_events")

_SKIP = {"/skip", "-", ""}


def _btn_time(e: Event) -> str:
    return format_short(e.starts_at, e.tz)


def _detail_text(lang: str, e: Event) -> str:
    return t(
        lang,
        "admin_events.detail",
        title=html.escape(e.title),
        time=format_range(e.starts_at, e.ends_at, e.tz),
        location=html.escape(e.location or "—"),
        signup=e.signup_count,
        capacity=e.capacity,
        waitlist=e.waitlist_count,
        status=e.status,
    )


# --------------------------------------------------------------------------
# List / detail / close / cancel
# --------------------------------------------------------------------------
@router.message(
    F.chat.type == "private",
    IsRegistered(),
    IsAdmin(),
    StateFilter(None),
    F.text.in_(label_set("menu.events_admin")),
)
async def open_admin_events(message: Message, db_user: User, session) -> None:
    await _render_admin_list(message, db_user, session, page=1)


async def _render_admin_list(
    target, db_user: User, session, *, page: int, edit: bool = False
) -> None:
    lang = db_user.language
    events, pages = await EventService(session).list_for_admin(page=page)
    if not events:
        text = t(lang, "admin_events.list_empty")
        kb = admin_events_list_kb(lang, [], 1, 1, fmt=_btn_time)
        await (target.edit_text if edit else target.answer)(text, reply_markup=kb)
        return
    kb = admin_events_list_kb(lang, events, page, pages, fmt=_btn_time)
    await (target.edit_text if edit else target.answer)(
        t(lang, "admin_events.list_title"), reply_markup=kb
    )


@router.callback_query(F.data.startswith("ae:"), IsAdmin())
async def admin_events_callback(
    query: CallbackQuery, state: FSMContext, db_user: User, session, bot, after_commit_tasks
) -> None:
    if not query.message:
        await query.answer()
        return
    lang = db_user.language
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "close" and len(parts) == 2:
        await query.message.edit_reply_markup(reply_markup=None)
        await query.answer()
        return
    if action == "new":
        await state.set_state(AdminEventStates.title)
        await query.message.answer(t(lang, "admin_events.new_title_prompt"))
        await query.answer()
        return
    if action == "edit":
        await query.message.edit_text(
            t(lang, "admin_events.edit_pick_field"),
            reply_markup=admin_event_edit_fields_kb(lang, _int(parts, 2, 0)),
        )
        await query.answer()
        return
    if action == "ef":  # start editing one field: ae:ef:<event_id>:<field>
        eid, field = _int(parts, 2, 0), parts[3] if len(parts) > 3 else ""
        event = await EventService(session).get(eid)
        if not event:
            await query.answer(t(lang, "shifts.not_found"), show_alert=True)
            return
        await state.set_state(AdminEventEditStates.value)
        await state.update_data(ev_edit_id=eid, ev_edit_field=field, ev_edit_tz=event.tz)
        prompt = {
            "title": "admin_events.new_title_prompt",
            "description": "admin_events.new_description_prompt",
            "location": "admin_events.new_location_prompt",
            "capacity": "admin_events.new_capacity_prompt",
            "time": "admin_events.new_starts_prompt",
        }.get(field, "errors.generic")
        await query.message.answer(t(lang, prompt, tz=event.tz))
        await query.answer()
        return
    if action == "list":
        await _render_admin_list(query.message, db_user, session, page=_int(parts, 2, 1), edit=True)
        await query.answer()
        return
    if action == "v":
        await _show_admin_detail(query, db_user, session, _int(parts, 2, 0))
        return
    if action == "close":
        ev, err = await EventService(session).close(_int(parts, 2, 0))
        if err:
            await query.answer(t(lang, err), show_alert=True)
            return
        await audit_service.record(
            session,
            actor_telegram_id=query.from_user.id,
            action="event_close",
            target_type="event",
            target_id=ev.id,
        )
        await query.answer(t(lang, "admin_events.closed"), show_alert=True)
        await _show_admin_detail(query, db_user, session, ev.id)
        return
    if action == "cancel":
        eid = _int(parts, 2, 0)
        await query.message.edit_text(
            t(lang, "admin_events.cancel_confirm"),
            reply_markup=admin_event_cancel_confirm_kb(lang, eid),
        )
        await query.answer()
        return
    if action == "cancelyes":
        eid = _int(parts, 2, 0)
        recipients, err = await EventService(session).cancel(eid)
        if err:
            await query.answer(t(lang, err), show_alert=True)
            return
        after_commit_tasks.append(reminder_service.unschedule(eid))
        for tid, ulang, title in recipients:
            after_commit_tasks.append(_notify_cancel(bot, tid, ulang, title))
        await audit_service.record(
            session,
            actor_telegram_id=query.from_user.id,
            action="event_cancel",
            target_type="event",
            target_id=eid,
            summary=f"notified={len(recipients)}",
        )
        await query.answer(t(lang, "admin_events.cancelled"), show_alert=True)
        await _show_admin_detail(query, db_user, session, eid)
        return
    await query.answer()


async def _show_admin_detail(query: CallbackQuery, db_user: User, session, event_id: int) -> None:
    lang = db_user.language
    ev = await EventService(session).get(event_id)
    if not ev:
        await query.answer(t(lang, "shifts.not_found"), show_alert=True)
        return
    with contextlib.suppress(Exception):
        await query.message.edit_text(
            _detail_text(lang, ev),
            reply_markup=admin_event_detail_kb(lang, event_id),
            parse_mode="HTML",
        )


def _notify_cancel(bot, telegram_id: int, lang: str, title: str):
    async def _job() -> None:
        try:
            await bot.send_message(telegram_id, t(lang, "shifts.cancelled_by_admin", title=title))
        except Exception as exc:
            logger.info("cancel notify failed: %s", exc)

    return _job()


# --------------------------------------------------------------------------
# Edit FSM (single field; "time" collects start then end and reschedules reminders)
# --------------------------------------------------------------------------
@router.message(IsAdmin(), StateFilter(AdminEventEditStates.value), F.text)
async def edit_value(
    message: Message, state: FSMContext, db_user: User, session, after_commit_tasks
) -> None:
    lang = db_user.language
    data = await state.get_data()
    eid, field = int(data["ev_edit_id"]), data["ev_edit_field"]
    raw = message.text.strip()
    svc = EventService(session)

    if field in ("title", "description", "location"):
        _, err = await svc.set_text_field(eid, field, raw)
    elif field == "capacity":
        if not raw.isdigit():
            await message.answer(t(lang, "admin_events.bad_capacity"))
            return
        _, err = await svc.set_capacity(eid, int(raw))
    elif field == "time":
        dt = parse_local_to_utc(raw, data["ev_edit_tz"])
        if dt is None:
            await message.answer(t(lang, "shifts.bad_datetime"))
            return
        await state.update_data(ev_starts_iso=dt.isoformat())
        await state.set_state(AdminEventEditStates.value2)
        await message.answer(t(lang, "admin_events.new_ends_prompt", tz=data["ev_edit_tz"]))
        return
    else:
        err = "errors.generic"

    await _finish_edit(message, state, db_user, session, after_commit_tasks, eid, err)


@router.message(IsAdmin(), StateFilter(AdminEventEditStates.value2), F.text)
async def edit_value2(
    message: Message, state: FSMContext, db_user: User, session, after_commit_tasks
) -> None:
    lang = db_user.language
    data = await state.get_data()
    eid = int(data["ev_edit_id"])
    ends = parse_local_to_utc(message.text, data["ev_edit_tz"])
    if ends is None:
        await message.answer(t(lang, "shifts.bad_datetime"))
        return
    starts = datetime.fromisoformat(data["ev_starts_iso"])
    ev, err = await EventService(session).set_times(eid, starts, ends)
    if not err and ev is not None:
        after_commit_tasks.append(reminder_service.reschedule(eid, starts, ends))
    await _finish_edit(message, state, db_user, session, after_commit_tasks, eid, err)


async def _finish_edit(
    message: Message,
    state: FSMContext,
    db_user: User,
    session,
    after_commit_tasks,
    eid: int,
    err: str,
) -> None:
    lang = db_user.language
    if err:
        await message.answer(t(lang, err))
        await state.clear()
        return
    await audit_service.record(
        session,
        actor_telegram_id=db_user.telegram_id,
        action="event_edit",
        target_type="event",
        target_id=eid,
    )
    await state.clear()
    await message.answer(
        t(lang, "admin_events.edit_saved"), reply_markup=main_menu_kb(lang, db_user)
    )


# --------------------------------------------------------------------------
# Creation FSM
# --------------------------------------------------------------------------
@router.message(IsAdmin(), StateFilter(AdminEventStates, AdminEventEditStates), F.text == "/cancel")
async def event_cancel_fsm(message: Message, state: FSMContext, db_user: User) -> None:
    await state.clear()
    await message.answer(
        t(db_user.language, "admin_projects.cancel"),
        reply_markup=main_menu_kb(db_user.language, db_user),
    )


@router.message(IsAdmin(), StateFilter(AdminEventStates.title), F.text)
async def event_title(message: Message, state: FSMContext, db_user: User) -> None:
    await state.update_data(title=message.text.strip()[:255])
    await state.set_state(AdminEventStates.description)
    await message.answer(t(db_user.language, "admin_events.new_description_prompt"))


@router.message(IsAdmin(), StateFilter(AdminEventStates.description), F.text)
async def event_description(message: Message, state: FSMContext, db_user: User) -> None:
    desc = "" if message.text.strip() in _SKIP else message.text.strip()
    await state.update_data(description=desc)
    await state.set_state(AdminEventStates.location)
    await message.answer(t(db_user.language, "admin_events.new_location_prompt"))


@router.message(IsAdmin(), StateFilter(AdminEventStates.location), F.text)
async def event_location(message: Message, state: FSMContext, db_user: User) -> None:
    loc = "" if message.text.strip() in _SKIP else message.text.strip()[:512]
    await state.update_data(location=loc)
    await state.set_state(AdminEventStates.tz)
    await message.answer(
        t(db_user.language, "admin_events.new_tz_prompt", default=get_settings().default_event_tz)
    )


@router.message(IsAdmin(), StateFilter(AdminEventStates.tz), F.text)
async def event_tz(message: Message, state: FSMContext, db_user: User) -> None:
    lang = db_user.language
    raw = message.text.strip()
    tz = get_settings().default_event_tz if raw in _SKIP else raw
    if not valid_tz(tz):
        await message.answer(t(lang, "shifts.bad_tz"))
        return
    await state.update_data(tz=tz)
    await state.set_state(AdminEventStates.starts_at)
    await message.answer(t(lang, "admin_events.new_starts_prompt", tz=tz))


@router.message(IsAdmin(), StateFilter(AdminEventStates.starts_at), F.text)
async def event_starts(message: Message, state: FSMContext, db_user: User) -> None:
    lang = db_user.language
    data = await state.get_data()
    dt = parse_local_to_utc(message.text, data["tz"])
    if dt is None:
        await message.answer(t(lang, "shifts.bad_datetime"))
        return
    await state.update_data(starts_iso=dt.isoformat())
    await state.set_state(AdminEventStates.ends_at)
    await message.answer(t(lang, "admin_events.new_ends_prompt", tz=data["tz"]))


@router.message(IsAdmin(), StateFilter(AdminEventStates.ends_at), F.text)
async def event_ends(message: Message, state: FSMContext, db_user: User) -> None:
    lang = db_user.language
    data = await state.get_data()
    dt = parse_local_to_utc(message.text, data["tz"])
    if dt is None:
        await message.answer(t(lang, "shifts.bad_datetime"))
        return
    await state.update_data(ends_iso=dt.isoformat())
    await state.set_state(AdminEventStates.capacity)
    await message.answer(t(lang, "admin_events.new_capacity_prompt"))


@router.message(IsAdmin(), StateFilter(AdminEventStates.capacity), F.text)
async def event_capacity(message: Message, state: FSMContext, db_user: User) -> None:
    lang = db_user.language
    raw = message.text.strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(t(lang, "admin_events.bad_capacity"))
        return
    await state.update_data(capacity=int(raw))
    data = await state.get_data()
    starts = datetime.fromisoformat(data["starts_iso"])
    summary = t(
        lang,
        "admin_events.confirm",
        title=html.escape(data["title"]),
        time=format_range(starts, datetime.fromisoformat(data["ends_iso"]), data["tz"]),
        location=html.escape(data.get("location") or "—"),
        capacity=data["capacity"],
    )
    await state.set_state(AdminEventStates.confirm)
    await message.answer(summary, parse_mode="HTML")


@router.message(IsAdmin(), StateFilter(AdminEventStates.confirm), F.text == "/yes")
async def event_confirm(
    message: Message, state: FSMContext, db_user: User, session, after_commit_tasks
) -> None:
    lang = db_user.language
    data = await state.get_data()
    starts = datetime.fromisoformat(data["starts_iso"])
    ends = datetime.fromisoformat(data["ends_iso"])
    event, err = await EventService(session).create(
        admin_user_id=db_user.id,
        title=data["title"],
        description=data.get("description", ""),
        location=data.get("location", ""),
        region_id=None,
        tz=data["tz"],
        starts_at=starts,
        ends_at=ends,
        capacity=data["capacity"],
    )
    if err or event is None:
        await message.answer(t(lang, err or "errors.generic"))
        await state.clear()
        return
    after_commit_tasks.append(reminder_service.schedule_for_event(event.id, starts, ends))
    await audit_service.record(
        session,
        actor_telegram_id=db_user.telegram_id,
        action="event_create",
        target_type="event",
        target_id=event.id,
        summary=data["title"][:100],
    )
    await state.clear()
    await message.answer(
        t(lang, "admin_events.created", title=html.escape(event.title)),
        reply_markup=main_menu_kb(lang, db_user),
        parse_mode="HTML",
    )


@router.message(IsAdmin(), StateFilter(AdminEventStates.confirm), F.text)
async def event_confirm_other(message: Message, db_user: User) -> None:
    await message.answer(t(db_user.language, "admin_events.confirm").split("\n")[-1])


def _int(parts: list[str], idx: int, default: int) -> int:
    try:
        return int(parts[idx])
    except (IndexError, ValueError):
        return default
