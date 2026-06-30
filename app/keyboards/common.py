from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.config import get_settings
from app.database.models import User, UserRole
from app.i18n import t

LANG_BTN_UZ = "🇺🇿 O'zbek tili"
LANG_BTN_RU = "🇷🇺 Русский"
LANG_PICK_LABELS: frozenset[str] = frozenset({LANG_BTN_UZ, LANG_BTN_RU})


def language_pick_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=LANG_BTN_UZ)], [KeyboardButton(text=LANG_BTN_RU)]],
        resize_keyboard=True,
    )


def main_menu_kb(lang: str, user: User | None) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [
            KeyboardButton(text=t(lang, "menu.projects")),
            KeyboardButton(text=t(lang, "menu.profile")),
        ],
        [KeyboardButton(text=t(lang, "menu.stats"))],
        [KeyboardButton(text=t(lang, "menu.faq"))],
        [
            KeyboardButton(text=t(lang, "menu.support")),
            KeyboardButton(text=t(lang, "menu.suggestion")),
        ],
        [
            KeyboardButton(text=t(lang, "menu.shifts")),
            KeyboardButton(text=t(lang, "menu.hours")),
        ],
    ]
    if user and user.role in (UserRole.admin.value, UserRole.super_admin.value):
        rows.append(
            [
                KeyboardButton(text=t(lang, "menu.broadcast")),
                KeyboardButton(text=t(lang, "menu.regions_admin")),
            ]
        )
        rows.append(
            [
                KeyboardButton(text=t(lang, "menu.applications_admin")),
                KeyboardButton(text=t(lang, "menu.projects_admin")),
            ]
        )
        rows.append(
            [
                KeyboardButton(text=t(lang, "menu.faq_admin")),
                KeyboardButton(text=t(lang, "menu.events_admin")),
            ]
        )
    s = get_settings()
    super_ids = s.parsed_super_admin_ids()
    if user and (user.role == UserRole.super_admin.value or user.telegram_id in super_ids):
        rows.append([KeyboardButton(text=t(lang, "menu.admin_panel"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def registration_phone_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "common.share_contact"), request_contact=True)]],
        resize_keyboard=True,
    )


def registration_skip_age_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "common.skip"))]],
        resize_keyboard=True,
    )


def registration_skip_bio_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t(lang, "common.skip"))]],
        resize_keyboard=True,
    )


def gender_reply_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, "gender.female_btn"))],
            [KeyboardButton(text=t(lang, "gender.male_btn"))],
            [KeyboardButton(text=t(lang, "gender.other_btn"))],
            [KeyboardButton(text=t(lang, "gender.unspecified_btn"))],
        ],
        resize_keyboard=True,
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def region_admin_root_inline(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "admin.regions.add"), callback_data="regadm:add")],
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.regions.edit"), callback_data="regadm:editlist"
                ),
                InlineKeyboardButton(
                    text=t(lang, "admin.regions.delete"), callback_data="regadm:dellist"
                ),
            ],
            [InlineKeyboardButton(text=t(lang, "admin.regions.list"), callback_data="regadm:list")],
            [InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="regadm:close")],
        ]
    )


def admin_panel_root_inline(lang: str, *, show_super: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text=t(lang, "admin.panel_regions"), callback_data="admpan:reg"),
            InlineKeyboardButton(text=t(lang, "admin.panel_faq"), callback_data="admpan:faq"),
        ],
        [InlineKeyboardButton(text=t(lang, "admin.panel_broadcast"), callback_data="admpan:bc")],
    ]
    if show_super:
        rows.append(
            [InlineKeyboardButton(text=t(lang, "admin.panel_super"), callback_data="admpan:super")]
        )
    rows.append(
        [InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="admpan:close")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_admin_root_inline(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(lang, "faq.cat_add"), callback_data="faqadm:addcat"),
                InlineKeyboardButton(text=t(lang, "faq.cat_edit"), callback_data="faqadm:editcat"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "faq.cat_delete"), callback_data="faqadm:delcat"),
            ],
            [
                InlineKeyboardButton(text=t(lang, "faq.add"), callback_data="faqadm:addfaq"),
                InlineKeyboardButton(text=t(lang, "faq.list_edit"), callback_data="faqadm:editfaq"),
            ],
            [InlineKeyboardButton(text=t(lang, "faq.list_delete"), callback_data="faqadm:delfaq")],
            [InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="faqadm:close")],
        ]
    )


def super_admin_user_actions(lang: str, telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.promote"), callback_data=f"sadm:adm:{telegram_id}"
                ),
                InlineKeyboardButton(
                    text=t(lang, "admin.demote"), callback_data=f"sadm:user:{telegram_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "admin.super_promote"), callback_data=f"sadm:super:{telegram_id}"
                )
            ],
            [InlineKeyboardButton(text=t(lang, "common.back"), callback_data="sadm:back")],
        ]
    )


def users_page_kb(lang: str, page: int, pages: int) -> InlineKeyboardMarkup:
    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="«", callback_data=f"sadm:page:{page-1}"))
    nav.append(
        InlineKeyboardButton(
            text=t(lang, "admin.page", page=page, pages=pages), callback_data="sadm:noop"
        )
    )
    if page < pages:
        nav.append(InlineKeyboardButton(text="»", callback_data=f"sadm:page:{page+1}"))
    return InlineKeyboardMarkup(inline_keyboard=[nav])
