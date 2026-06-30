"""
High-priority handlers: bypass FSM and unblock admins (registered first on dispatcher).
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import get_settings
from app.database.models import User, UserRole
from app.handlers.admin.super_admin import _build_list_markup
from app.handlers.filters import IsAdmin, IsSuperAdmin
from app.i18n import t
from app.keyboards.common import (
    admin_panel_root_inline,
    faq_admin_root_inline,
    main_menu_kb,
    region_admin_root_inline,
)
from app.services.region_service import RegionService
from app.services.user_service import UserService
from app.states.forms import BroadcastStates

logger = logging.getLogger(__name__)
router = Router(name="emergency")


def _lang(db_user: User | None, message: Message) -> str:
    if db_user:
        return db_user.language
    fu = message.from_user
    lc = (fu.language_code if fu else None) or "uz"
    return "ru" if lc.lower().startswith("ru") else "uz"


def _show_super_panel(from_user_id: int | None, db_user: User | None) -> bool:
    s = get_settings()
    if from_user_id is not None and from_user_id in s.parsed_super_admin_ids():
        return True
    return bool(db_user and db_user.role == UserRole.super_admin.value)


async def _resolve_db_user(message: Message, db_user: User | None, session) -> User | None:
    if db_user:
        return db_user
    fu = message.from_user
    if not fu:
        return None
    return await UserService(session).get_by_telegram_id(fu.id)


@router.message(Command("force_start"), F.chat.type == "private")
async def cmd_force_start(message: Message, state: FSMContext, db_user: User | None):
    await state.clear()
    lang = _lang(db_user, message)
    await message.answer(t(lang, "admin.force_start_ok"))


@router.message(Command("admin"), F.chat.type == "private", IsAdmin())
async def cmd_admin(message: Message, state: FSMContext, db_user: User | None, session):
    await state.clear()
    u = await _resolve_db_user(message, db_user, session)
    if not u:
        await message.answer(t("uz", "errors.generic"))
        return
    lang = u.language
    fu = message.from_user
    show_super = _show_super_panel(fu.id if fu else None, u)
    await message.answer(
        t(lang, "admin.panel_title"),
        reply_markup=admin_panel_root_inline(lang, show_super=show_super),
    )


@router.message(Command("add_region"), F.chat.type == "private", IsAdmin())
async def cmd_add_region(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db_user: User | None,
    session,
):
    await state.clear()
    u = await _resolve_db_user(message, db_user, session)
    if not u:
        await message.answer(t("uz", "errors.generic"))
        return
    lang = u.language
    raw = (command.args or "").strip()
    if "|" not in raw:
        await message.answer(t(lang, "admin.add_region_usage"))
        return
    left, right = raw.split("|", 1)
    uz = left.strip()
    ru = right.strip()
    if len(uz) < 2 or len(ru) < 2:
        await message.answer(t(lang, "admin.add_region_bad"))
        return
    await RegionService(session).create(uz, ru)
    await message.answer(t(lang, "admin.add_region_ok"), reply_markup=main_menu_kb(lang, u))
    logger.info("Region created via /add_region by telegram_id=%s", u.telegram_id)


@router.callback_query(F.data == "admpan:close", IsAdmin())
async def admpan_close(query: CallbackQuery, db_user: User | None, session):
    u = db_user
    if not u and query.from_user:
        u = await UserService(session).get_by_telegram_id(query.from_user.id)
    if not query.message:
        await query.answer()
        return
    await query.message.edit_reply_markup(reply_markup=None)
    await query.answer()
    if u:
        await query.message.answer(
            t(u.language, "common.menu_hint"), reply_markup=main_menu_kb(u.language, u)
        )


@router.callback_query(F.data == "admpan:reg", IsAdmin())
async def admpan_regions(query: CallbackQuery, db_user: User | None, session):
    u = db_user
    if not u and query.from_user:
        u = await UserService(session).get_by_telegram_id(query.from_user.id)
    if not u or not query.message:
        await query.answer()
        return
    lang = u.language
    await query.message.answer(
        t(lang, "admin.regions.title"), reply_markup=region_admin_root_inline(lang)
    )
    await query.answer()


@router.callback_query(F.data == "admpan:faq", IsAdmin())
async def admpan_faq(query: CallbackQuery, db_user: User | None, session):
    u = db_user
    if not u and query.from_user:
        u = await UserService(session).get_by_telegram_id(query.from_user.id)
    if not u or not query.message:
        await query.answer()
        return
    lang = u.language
    await query.message.answer(t(lang, "faq.admin_title"), reply_markup=faq_admin_root_inline(lang))
    await query.answer()


@router.callback_query(F.data == "admpan:bc", IsAdmin())
async def admpan_broadcast(query: CallbackQuery, state: FSMContext, db_user: User | None, session):
    u = db_user
    if not u and query.from_user:
        u = await UserService(session).get_by_telegram_id(query.from_user.id)
    if not u or not query.message:
        await query.answer()
        return
    await state.set_state(BroadcastStates.content)
    await query.message.answer(t(u.language, "broadcast.send_text"))
    await query.answer()


@router.callback_query(F.data == "admpan:super", IsSuperAdmin())
async def admpan_super(query: CallbackQuery, state: FSMContext, db_user: User | None, session):
    """Open super list only for super admins."""
    u = db_user
    if not u and query.from_user:
        u = await UserService(session).get_by_telegram_id(query.from_user.id)
    if not u or not query.message or not query.from_user:
        await query.answer()
        return
    await state.update_data(sadm_q=None)
    text, markup = await _build_list_markup(session, state, u, 1)
    await query.message.answer(text, reply_markup=markup)
    await query.answer()
