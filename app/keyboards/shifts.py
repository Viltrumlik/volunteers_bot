"""Inline keyboards for the shift-scheduling + hours feature.

Callback prefixes (kept short, < 64 bytes): ``sh:`` volunteer, ``hr:`` hours,
``ae:`` admin event, ``aa:`` admin attendance.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Event, EventSignup
from app.i18n import t


def _pager(lang: str, prefix: str, page: int, pages: int) -> list[InlineKeyboardButton]:
    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"{prefix}{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="sh:noop"))
    if page < pages:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"{prefix}{page + 1}"))
    return nav


# --------------------------------------------------------------------------
# Volunteer
# --------------------------------------------------------------------------
def shifts_list_kb(
    lang: str, events: list[Event], page: int, pages: int, *, fmt
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"{e.title} · {fmt(e)}", callback_data=f"sh:v:{e.id}")]
        for e in events
    ]
    if pages > 1:
        rows.append(_pager(lang, "sh:list:", page, pages))
    rows.append(
        [InlineKeyboardButton(text=t(lang, "shifts.btn_my_shifts"), callback_data="sh:my:1")]
    )
    rows.append([InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="sh:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shift_detail_kb(
    lang: str,
    event_id: int,
    *,
    can_signup: bool,
    can_waitlist: bool,
    can_cancel: bool,
    can_checkin: bool,
    can_checkout: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_signup:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "shifts.btn_signup"), callback_data=f"sh:j:{event_id}"
                )
            ]
        )
    elif can_waitlist:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "shifts.btn_waitlist"), callback_data=f"sh:w:{event_id}"
                )
            ]
        )
    if can_checkin:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "shifts.btn_checkin"), callback_data=f"sh:ci:{event_id}"
                )
            ]
        )
    if can_checkout:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "shifts.btn_checkout"), callback_data=f"sh:co:{event_id}"
                )
            ]
        )
    if can_cancel:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "shifts.btn_cancel"), callback_data=f"sh:c:{event_id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=t(lang, "common.back"), callback_data="sh:list:1")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_shifts_kb(lang: str, signups: list[EventSignup], *, fmt) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{s.event.title} · {fmt(s.event)} [{s.status}]",
                callback_data=f"sh:v:{s.event_id}",
            )
        ]
        for s in signups
    ]
    rows.append([InlineKeyboardButton(text=t(lang, "common.back"), callback_data="sh:list:1")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def hours_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(lang, "hours.btn_lb_all"), callback_data="hr:lb:all"),
                InlineKeyboardButton(text=t(lang, "hours.btn_lb_30"), callback_data="hr:lb:30"),
            ],
            [InlineKeyboardButton(text=t(lang, "hours.btn_my_hours"), callback_data="hr:me")],
            [InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="hr:close")],
        ]
    )


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------
def admin_events_list_kb(
    lang: str, events: list[Event], page: int, pages: int, *, fmt
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"{e.title} · {fmt(e)} [{e.status}]", callback_data=f"ae:v:{e.id}"
            )
        ]
        for e in events
    ]
    if pages > 1:
        rows.append(_pager(lang, "ae:list:", page, pages))
    rows.append(
        [InlineKeyboardButton(text=t(lang, "admin_events.btn_new"), callback_data="ae:new")]
    )
    rows.append([InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="ae:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_event_detail_kb(lang: str, event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin_events.btn_roster"), callback_data=f"aa:v:{event_id}:1"
                ),
                InlineKeyboardButton(
                    text=t(lang, "admin_events.btn_edit"), callback_data=f"ae:edit:{event_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "admin_events.btn_close"), callback_data=f"ae:close:{event_id}"
                ),
                InlineKeyboardButton(
                    text=t(lang, "admin_events.btn_cancel"), callback_data=f"ae:cancel:{event_id}"
                ),
            ],
            [InlineKeyboardButton(text=t(lang, "common.back"), callback_data="ae:list:1")],
        ]
    )


def admin_event_edit_fields_kb(lang: str, event_id: int) -> InlineKeyboardMarkup:
    def _row(field: str) -> list[InlineKeyboardButton]:
        return [
            InlineKeyboardButton(
                text=t(lang, f"admin_events.field_{field}"),
                callback_data=f"ae:ef:{event_id}:{field}",
            )
        ]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            _row("title"),
            _row("description"),
            _row("location"),
            _row("capacity"),
            _row("time"),
            [InlineKeyboardButton(text=t(lang, "common.back"), callback_data=f"ae:v:{event_id}")],
        ]
    )


def admin_event_cancel_confirm_kb(lang: str, event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin_events.btn_cancel"),
                    callback_data=f"ae:cancelyes:{event_id}",
                )
            ],
            [InlineKeyboardButton(text=t(lang, "common.back"), callback_data=f"ae:v:{event_id}")],
        ]
    )


def roster_kb(
    lang: str, signups: list[EventSignup], event_id: int, page: int, pages: int
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"{s.user.full_name} — {s.status}", callback_data=f"aa:s:{s.id}:{event_id}"
            )
        ]
        for s in signups
    ]
    if pages > 1:
        rows.append(_pager(lang, f"aa:v:{event_id}:", page, pages))
    rows.append(
        [InlineKeyboardButton(text=t(lang, "common.back"), callback_data=f"ae:v:{event_id}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def signup_actions_kb(lang: str, signup_id: int, event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin_attendance.btn_checkin"),
                    callback_data=f"aa:mark:{signup_id}:checked_in:{event_id}",
                ),
                InlineKeyboardButton(
                    text=t(lang, "admin_attendance.btn_checkout"),
                    callback_data=f"aa:mark:{signup_id}:checked_out:{event_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "admin_attendance.btn_noshow"),
                    callback_data=f"aa:mark:{signup_id}:no_show:{event_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "admin_attendance.btn_adjust"),
                    callback_data=f"aa:adj:{signup_id}:{event_id}",
                )
            ],
            [InlineKeyboardButton(text=t(lang, "common.back"), callback_data=f"aa:v:{event_id}:1")],
        ]
    )
