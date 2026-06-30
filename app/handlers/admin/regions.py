import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.models import User
from app.handlers.filters import IsAdmin
from app.handlers.labels import label_set
from app.i18n import t
from app.keyboards.common import main_menu_kb, region_admin_root_inline
from app.services.region_service import RegionService
from app.states.forms import RegionAdminStates

logger = logging.getLogger(__name__)
router = Router(name="admin_regions")


def _region_rows(regions: list, lang: str, prefix: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for r in regions:
        label = r.name_ru if lang == "ru" else r.name_uz
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"{prefix}:{r.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(
    F.chat.type == "private",
    IsAdmin(),
    StateFilter(None),
    F.text.in_(label_set("menu.regions_admin")),
)
async def regions_admin_entry(message: Message, db_user: User):
    lang = db_user.language
    await message.answer(
        t(lang, "admin.regions.title"), reply_markup=region_admin_root_inline(lang)
    )


@router.callback_query(F.data == "regadm:close", IsAdmin())
async def regadm_close(query: CallbackQuery, db_user: User):
    await query.message.edit_reply_markup(reply_markup=None)
    await query.answer()
    await query.message.answer(
        t(db_user.language, "common.menu_hint"),
        reply_markup=main_menu_kb(db_user.language, db_user),
    )


@router.callback_query(F.data == "regadm:add", IsAdmin())
async def regadm_add(query: CallbackQuery, state: FSMContext, db_user: User):
    await state.set_state(RegionAdminStates.add_name_uz)
    await query.message.answer(t(db_user.language, "admin.regions.enter_uz"))
    await query.answer()


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(RegionAdminStates.add_name_uz), F.text
)
async def regadm_add_uz(message: Message, state: FSMContext, db_user: User):
    await state.update_data(reg_uz=message.text.strip())
    await state.set_state(RegionAdminStates.add_name_ru)
    await message.answer(t(db_user.language, "admin.regions.enter_ru"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(RegionAdminStates.add_name_ru), F.text
)
async def regadm_add_ru(message: Message, state: FSMContext, db_user: User, session):
    lang = db_user.language
    uz = (await state.get_data()).get("reg_uz", "")
    ru = message.text.strip()
    if len(uz) < 2 or len(ru) < 2:
        await state.clear()
        await message.answer(t(lang, "errors.generic"), reply_markup=main_menu_kb(lang, db_user))
        return
    await RegionService(session).create(uz, ru)
    await state.clear()
    await message.answer(t(lang, "admin.regions.saved"), reply_markup=main_menu_kb(lang, db_user))
    logger.info("Region created by %s", db_user.telegram_id)


@router.callback_query(F.data == "regadm:editlist", IsAdmin())
async def regadm_edit_list(query: CallbackQuery, db_user: User, session, state: FSMContext):
    lang = db_user.language
    regs = await RegionService(session).list_all_ordered()
    if not regs:
        await query.answer(t(lang, "admin.regions.empty"), show_alert=True)
        return
    await state.set_state(RegionAdminStates.edit_pick)
    await query.message.answer(
        t(lang, "admin.regions.pick_edit"), reply_markup=_region_rows(regs, lang, "reged")
    )
    await query.answer()


@router.callback_query(
    F.data.startswith("reged:"), IsAdmin(), StateFilter(RegionAdminStates.edit_pick)
)
async def regadm_edit_pick(query: CallbackQuery, state: FSMContext, db_user: User):
    try:
        rid = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer()
        return
    await state.update_data(reg_edit_id=rid)
    await state.set_state(RegionAdminStates.edit_name_uz)
    await query.message.answer(t(db_user.language, "admin.regions.new_uz"))
    await query.answer()


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(RegionAdminStates.edit_name_uz), F.text
)
async def regadm_edit_uz(message: Message, state: FSMContext, db_user: User):
    await state.update_data(reg_new_uz=message.text.strip())
    await state.set_state(RegionAdminStates.edit_name_ru)
    await message.answer(t(db_user.language, "admin.regions.new_ru"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(RegionAdminStates.edit_name_ru), F.text
)
async def regadm_edit_ru(message: Message, state: FSMContext, db_user: User, session):
    lang = db_user.language
    data = await state.get_data()
    rid = data["reg_edit_id"]
    ok = await RegionService(session).update_names(
        rid, name_uz=data["reg_new_uz"], name_ru=message.text.strip()
    )
    await state.clear()
    await message.answer(
        t(lang, "admin.regions.updated") if ok else t(lang, "errors.generic"),
        reply_markup=main_menu_kb(lang, db_user),
    )


@router.callback_query(F.data == "regadm:dellist", IsAdmin())
async def regadm_del_list(query: CallbackQuery, db_user: User, session, state: FSMContext):
    lang = db_user.language
    regs = await RegionService(session).list_all_ordered()
    if not regs:
        await query.answer(t(lang, "admin.regions.empty"), show_alert=True)
        return
    await state.set_state(RegionAdminStates.delete_pick)
    await query.message.answer(
        t(lang, "admin.regions.pick_delete"), reply_markup=_region_rows(regs, lang, "regdel")
    )
    await query.answer()


@router.callback_query(
    F.data.startswith("regdel:"), IsAdmin(), StateFilter(RegionAdminStates.delete_pick)
)
async def regadm_del_do(query: CallbackQuery, state: FSMContext, db_user: User, session):
    lang = db_user.language
    try:
        rid = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer()
        return
    ok = await RegionService(session).set_active(rid, False)
    await state.clear()
    await query.message.answer(
        t(lang, "admin.regions.deactivated") if ok else t(lang, "errors.generic"),
        reply_markup=main_menu_kb(lang, db_user),
    )
    await query.answer()


@router.callback_query(F.data == "regadm:list", IsAdmin())
async def regadm_list(query: CallbackQuery, db_user: User, session):
    lang = db_user.language
    regs = await RegionService(session).list_all_ordered()
    if not regs:
        await query.answer(t(lang, "admin.regions.empty"), show_alert=True)
        return
    lines = [t(lang, "admin.regions.list_title")]
    for r in regs:
        st = "✓" if r.is_active else "✗"
        lines.append(f"{st} <code>{r.id}</code> {r.name_uz} / {r.name_ru}")
    await query.message.answer(
        "\n".join(lines), parse_mode="HTML", reply_markup=main_menu_kb(lang, db_user)
    )
    await query.answer()
