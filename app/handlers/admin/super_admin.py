import html
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import get_settings
from app.database.models import Region, User, UserRole
from app.handlers.filters import IsRegistered, IsSuperAdmin
from app.handlers.labels import label_set
from app.i18n import t
from app.keyboards.common import super_admin_user_actions, users_page_kb
from app.logging_config import mask_user_id
from app.services import audit_service
from app.services.user_service import UserService
from app.states.forms import SuperAdminStates

logger = logging.getLogger(__name__)
router = Router(name="super_admin")


async def _build_list_markup(
    session, state: FSMContext, db_user: User, page: int
) -> tuple[str, InlineKeyboardMarkup]:
    data = await state.get_data()
    q = data.get("sadm_q")
    users, pages = await UserService(session).list_users_page(page=page, per_page=6, query=q)
    await state.update_data(sadm_page=page)
    lang = db_user.language
    if not users:
        text = t(lang, "admin.users") + "\n—"
        rows: list[list[InlineKeyboardButton]] = []
    else:
        lines = [t(lang, "admin.users")]
        rows = []
        for u in users:
            label = f"{u.full_name[:26]} · {u.telegram_id}"
            rows.append(
                [InlineKeyboardButton(text=label[:64], callback_data=f"sadm:u:{u.telegram_id}")]
            )
        text = "\n".join(lines)
    rows.extend(users_page_kb(lang, page, pages).inline_keyboard)
    rows.append(
        [
            InlineKeyboardButton(
                text="🔍 " + t(lang, "admin.search_prompt")[:40], callback_data="sadm:search"
            )
        ]
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    IsSuperAdmin(),
    StateFilter(None),
    F.text.in_(label_set("menu.admin_panel")),
)
async def open_super_panel(message: Message, state: FSMContext, db_user: User, session):
    await state.update_data(sadm_q=None)
    text, markup = await _build_list_markup(session, state, db_user, 1)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("sadm:page:"), IsSuperAdmin())
async def super_page(query: CallbackQuery, state: FSMContext, db_user: User, session):
    try:
        page = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        await query.answer()
        return
    text, markup = await _build_list_markup(session, state, db_user, page)
    await query.message.edit_text(text, reply_markup=markup)
    await query.answer()


@router.callback_query(F.data == "sadm:noop", IsSuperAdmin())
async def super_noop(query: CallbackQuery):
    await query.answer()


@router.callback_query(F.data == "sadm:search", IsSuperAdmin())
async def super_search_start(query: CallbackQuery, state: FSMContext, db_user: User):
    await state.set_state(SuperAdminStates.search_query)
    await query.message.answer(t(db_user.language, "admin.search_prompt"))
    await query.answer()


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    IsSuperAdmin(),
    StateFilter(SuperAdminStates.search_query),
    F.text,
)
async def super_search_apply(message: Message, state: FSMContext, db_user: User, session):
    raw = (message.text or "").strip()
    q = raw if raw else None
    await state.update_data(sadm_q=q)
    await state.set_state(None)
    text, markup = await _build_list_markup(session, state, db_user, 1)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("sadm:u:"), IsSuperAdmin())
async def super_open_user(query: CallbackQuery, db_user: User, session):
    try:
        tid = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        await query.answer()
        return
    u = await UserService(session).get_by_telegram_id(tid)
    lang = db_user.language
    if not u:
        await query.answer("—", show_alert=True)
        return
    un = f"@{u.username}" if u.username else "—"
    reg = await session.get(Region, u.region_id) if u.region_id is not None else None
    rtxt = f"{reg.name_uz} / {reg.name_ru}" if reg else "—"
    text = (
        f"{html.escape(u.full_name)}\nID: <code>{u.telegram_id}</code>\n{html.escape(un)}\n"
        f"Phone: {html.escape(u.phone or '—')}\nRegion: {html.escape(rtxt)}\nRole: {u.role}"
    )
    await query.message.edit_text(text, reply_markup=super_admin_user_actions(lang, u.telegram_id))
    await query.answer()


@router.callback_query(F.data == "sadm:back", IsSuperAdmin())
async def super_back(query: CallbackQuery, state: FSMContext, db_user: User, session):
    data = await state.get_data()
    page = int(data.get("sadm_page") or 1)
    text, markup = await _build_list_markup(session, state, db_user, page)
    await query.message.edit_text(text, reply_markup=markup)
    await query.answer()


def _blocked_env_super(tid: int) -> bool:
    return tid in get_settings().parsed_super_admin_ids()


@router.callback_query(F.data.startswith("sadm:adm:"), IsSuperAdmin())
async def super_set_admin(query: CallbackQuery, session, db_user: User):
    tid = int(query.data.split(":")[2])
    if tid == query.from_user.id:
        await query.answer("—", show_alert=True)
        return
    if _blocked_env_super(tid):
        await query.answer("env super", show_alert=True)
        return
    await UserService(session).set_role(tid, UserRole.admin.value)
    await audit_service.record(
        session,
        actor_telegram_id=query.from_user.id,
        action="role_set",
        target_type="user",
        target_id=tid,
        summary="-> admin",
    )
    await query.answer(t(db_user.language, "admin.role_updated"))
    logger.info(
        "role->admin target=%s actor=%s", mask_user_id(tid), mask_user_id(query.from_user.id)
    )


@router.callback_query(F.data.startswith("sadm:user:"), IsSuperAdmin())
async def super_set_user(query: CallbackQuery, session, db_user: User):
    tid = int(query.data.split(":")[2])
    if tid == query.from_user.id:
        await query.answer("—", show_alert=True)
        return
    if _blocked_env_super(tid):
        await query.answer("env super", show_alert=True)
        return
    await UserService(session).set_role(tid, UserRole.user.value)
    await audit_service.record(
        session,
        actor_telegram_id=query.from_user.id,
        action="role_set",
        target_type="user",
        target_id=tid,
        summary="-> user",
    )
    await query.answer(t(db_user.language, "admin.role_updated"))
    logger.info(
        "role->user target=%s actor=%s", mask_user_id(tid), mask_user_id(query.from_user.id)
    )


@router.callback_query(F.data.startswith("sadm:super:"), IsSuperAdmin())
async def super_set_super(query: CallbackQuery, session, db_user: User):
    tid = int(query.data.split(":")[2])
    if tid == query.from_user.id:
        await query.answer("—", show_alert=True)
        return
    await UserService(session).set_role(tid, UserRole.super_admin.value)
    await audit_service.record(
        session,
        actor_telegram_id=query.from_user.id,
        action="role_set",
        target_type="user",
        target_id=tid,
        summary="-> super_admin",
    )
    await query.answer(t(db_user.language, "admin.role_updated"))
    logger.info(
        "role->super target=%s actor=%s", mask_user_id(tid), mask_user_id(query.from_user.id)
    )
