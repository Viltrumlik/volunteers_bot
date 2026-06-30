import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.models import User
from app.handlers.filters import IsAdmin
from app.i18n import t
from app.keyboards.common import main_menu_kb
from app.services.faq_category_service import FAQCategoryService
from app.services.faq_service import FAQService
from app.states.forms import FAQAdminStates, FAQCategoryAdminStates

logger = logging.getLogger(__name__)
router = Router(name="admin_faq")


def _cat_rows(cats: list, lang: str, prefix: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for c in cats:
        label = c.name_ru if lang == "ru" else c.name_uz
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"{prefix}:{c.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _faq_rows(faqs: list, lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for f in faqs:
        title = f.question_ru if lang == "ru" and f.question_ru else f.question_uz
        rows.append([InlineKeyboardButton(text=title[:64], callback_data=f"faqed:{f.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "faqadm:close", IsAdmin())
async def faqadm_close(query: CallbackQuery, db_user: User, state: FSMContext):
    await state.clear()
    await query.message.edit_reply_markup(reply_markup=None)
    await query.answer()
    await query.message.answer(
        t(db_user.language, "common.menu_hint"),
        reply_markup=main_menu_kb(db_user.language, db_user),
    )


# --- FAQ categories ---
@router.callback_query(F.data == "faqadm:addcat", IsAdmin())
async def faqadm_addcat(query: CallbackQuery, state: FSMContext, db_user: User):
    await state.set_state(FAQCategoryAdminStates.add_name_uz)
    await query.message.answer(t(db_user.language, "faq.cat_enter_uz"))
    await query.answer()


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQCategoryAdminStates.add_name_uz), F.text
)
async def faqcat_add_uz(message: Message, state: FSMContext, db_user: User):
    await state.update_data(fcat_uz=message.text.strip())
    await state.set_state(FAQCategoryAdminStates.add_name_ru)
    await message.answer(t(db_user.language, "faq.cat_enter_ru"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQCategoryAdminStates.add_name_ru), F.text
)
async def faqcat_add_ru(message: Message, state: FSMContext, db_user: User, session):
    lang = db_user.language
    data = await state.get_data()
    uz = data.get("fcat_uz", "")
    ru = message.text.strip()
    if len(uz) < 2 or len(ru) < 2:
        await state.clear()
        await message.answer(t(lang, "errors.generic"), reply_markup=main_menu_kb(lang, db_user))
        return
    await FAQCategoryService(session).create(uz, ru)
    await state.clear()
    await message.answer(t(lang, "faq.cat_saved"), reply_markup=main_menu_kb(lang, db_user))


@router.callback_query(F.data == "faqadm:editcat", IsAdmin())
async def faqadm_editcat(query: CallbackQuery, db_user: User, session, state: FSMContext):
    lang = db_user.language
    cats = await FAQCategoryService(session).list_all_ordered()
    if not cats:
        await query.answer(t(lang, "faq.no_categories"), show_alert=True)
        return
    await state.set_state(FAQCategoryAdminStates.edit_pick)
    await query.message.answer(
        t(lang, "faq.cat_pick_edit"), reply_markup=_cat_rows(cats, lang, "faqced")
    )
    await query.answer()


@router.callback_query(
    F.data.startswith("faqced:"), IsAdmin(), StateFilter(FAQCategoryAdminStates.edit_pick)
)
async def faqced_pick(query: CallbackQuery, state: FSMContext, db_user: User):
    try:
        cid = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer()
        return
    await state.update_data(fcat_edit_id=cid)
    await state.set_state(FAQCategoryAdminStates.edit_name_uz)
    await query.message.answer(t(db_user.language, "faq.cat_new_uz"))
    await query.answer()


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQCategoryAdminStates.edit_name_uz), F.text
)
async def faqcat_edit_uz(message: Message, state: FSMContext, db_user: User):
    await state.update_data(fcat_new_uz=message.text.strip())
    await state.set_state(FAQCategoryAdminStates.edit_name_ru)
    await message.answer(t(db_user.language, "faq.cat_new_ru"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQCategoryAdminStates.edit_name_ru), F.text
)
async def faqcat_edit_ru(message: Message, state: FSMContext, db_user: User, session):
    lang = db_user.language
    data = await state.get_data()
    cid = data["fcat_edit_id"]
    ok = await FAQCategoryService(session).update_names(
        cid, name_uz=data["fcat_new_uz"], name_ru=message.text.strip()
    )
    await state.clear()
    await message.answer(
        t(lang, "faq.cat_updated") if ok else t(lang, "errors.generic"),
        reply_markup=main_menu_kb(lang, db_user),
    )


@router.callback_query(F.data == "faqadm:delcat", IsAdmin())
async def faqadm_delcat(query: CallbackQuery, db_user: User, session, state: FSMContext):
    lang = db_user.language
    cats = await FAQCategoryService(session).list_all_ordered()
    if not cats:
        await query.answer(t(lang, "faq.no_categories"), show_alert=True)
        return
    await state.set_state(FAQCategoryAdminStates.delete_pick)
    await query.message.answer(
        t(lang, "faq.cat_pick_delete"), reply_markup=_cat_rows(cats, lang, "faqcdel")
    )
    await query.answer()


@router.callback_query(
    F.data.startswith("faqcdel:"), IsAdmin(), StateFilter(FAQCategoryAdminStates.delete_pick)
)
async def faqcdel_do(query: CallbackQuery, state: FSMContext, db_user: User, session):
    lang = db_user.language
    try:
        cid = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer()
        return
    ok = await FAQCategoryService(session).set_active(cid, False)
    await state.clear()
    await query.message.answer(
        t(lang, "faq.cat_deleted") if ok else t(lang, "errors.generic"),
        reply_markup=main_menu_kb(lang, db_user),
    )
    await query.answer()


# --- Add FAQ (pick category) ---
@router.callback_query(F.data == "faqadm:addfaq", IsAdmin())
async def faqadm_addfaq(query: CallbackQuery, db_user: User, session, state: FSMContext):
    lang = db_user.language
    cats = await FAQCategoryService(session).list_active_ordered()
    if not cats:
        await query.answer(t(lang, "faq.no_categories"), show_alert=True)
        return
    rows: list[list[InlineKeyboardButton]] = []
    for c in cats:
        label = c.name_ru if lang == "ru" else c.name_uz
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"faqadm:ncat:{c.id}")])
    await query.message.answer(
        t(lang, "faq.pick_category_for_faq"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await query.answer()


@router.callback_query(F.data.startswith("faqadm:ncat:"), IsAdmin())
async def faqadm_newcat_pick(query: CallbackQuery, state: FSMContext, db_user: User):
    try:
        cid = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        await query.answer()
        return
    await state.update_data(faq_cat_id=cid)
    await state.set_state(FAQAdminStates.add_question_uz)
    await query.message.answer(t(db_user.language, "faq.enter_q_uz"))
    await query.answer()


# --- FAQ message FSM (add / edit answers) ---
@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQAdminStates.add_question_uz), F.text
)
async def faq_add_q_uz(message: Message, state: FSMContext, db_user: User):
    lang = db_user.language
    await state.update_data(faq_q_uz=message.text.strip())
    await state.set_state(FAQAdminStates.add_answer_uz)
    await message.answer(t(lang, "faq.enter_a_uz"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQAdminStates.add_answer_uz), F.text
)
async def faq_add_a_uz(message: Message, state: FSMContext, db_user: User):
    lang = db_user.language
    await state.update_data(faq_a_uz=message.text.strip())
    await state.set_state(FAQAdminStates.add_question_ru)
    await message.answer(t(lang, "faq.enter_q_ru"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQAdminStates.add_question_ru), F.text
)
async def faq_add_q_ru(message: Message, state: FSMContext, db_user: User):
    lang = db_user.language
    text = (message.text or "").strip()
    if text == "/skip":
        await state.update_data(faq_q_ru=None)
    else:
        await state.update_data(faq_q_ru=text)
    await state.set_state(FAQAdminStates.add_answer_ru)
    await message.answer(t(lang, "faq.enter_a_ru"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQAdminStates.add_answer_ru), F.text
)
async def faq_add_a_ru(message: Message, state: FSMContext, db_user: User, session):
    lang = db_user.language
    data = await state.get_data()
    cid = data.get("faq_cat_id")
    if not cid:
        await state.clear()
        await message.answer(t(lang, "errors.generic"), reply_markup=main_menu_kb(lang, db_user))
        return
    q_ru = data.get("faq_q_ru")
    text = (message.text or "").strip()
    a_ru = None if text == "/skip" else text or None
    await FAQService(session).create(
        int(cid),
        question_uz=data["faq_q_uz"],
        answer_uz=data["faq_a_uz"],
        question_ru=q_ru,
        answer_ru=a_ru,
    )
    await state.clear()
    await message.answer(t(lang, "faq.saved"), reply_markup=main_menu_kb(lang, db_user))
    logger.info("FAQ created by admin telegram_id=%s", db_user.telegram_id)


# --- Edit FAQ ---
@router.callback_query(F.data == "faqadm:editfaq", IsAdmin())
async def faqadm_editfaq(query: CallbackQuery, db_user: User, session, state: FSMContext):
    lang = db_user.language
    cats = await FAQCategoryService(session).list_active_ordered()
    if not cats:
        await query.answer(t(lang, "faq.no_categories"), show_alert=True)
        return
    await state.set_state(FAQAdminStates.edit_pick_category)
    await query.message.answer(
        t(lang, "faq.pick_category_edit_faq"), reply_markup=_cat_rows(cats, lang, "faqadm:ecat")
    )
    await query.answer()


@router.callback_query(
    F.data.startswith("faqadm:ecat:"), IsAdmin(), StateFilter(FAQAdminStates.edit_pick_category)
)
async def faqadm_ecat(query: CallbackQuery, state: FSMContext, db_user: User, session):
    lang = db_user.language
    try:
        cid = int(query.data.split(":")[-1])
    except (IndexError, ValueError):
        await query.answer()
        return
    faqs = await FAQService(session).list_by_category_ordered(cid)
    if not faqs:
        await query.answer(t(lang, "faq.empty_category"), show_alert=True)
        return
    await state.update_data(faq_edit_cat=cid)
    await state.set_state(FAQAdminStates.edit_pick)
    await query.message.answer(t(lang, "faq.pick_to_edit"), reply_markup=_faq_rows(faqs, lang))
    await query.answer()


@router.callback_query(
    F.data.startswith("faqed:"), IsAdmin(), StateFilter(FAQAdminStates.edit_pick)
)
async def faq_edit_pick(query: CallbackQuery, state: FSMContext, db_user: User):
    lang = db_user.language
    try:
        fid = int(query.data.split(":", 1)[1])
    except ValueError:
        await query.answer()
        return
    await state.update_data(faq_edit_id=fid)
    await state.set_state(FAQAdminStates.edit_question)
    await query.message.answer(t(lang, "faq.new_question"))
    await query.answer()


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQAdminStates.edit_question), F.text
)
async def faq_edit_q(message: Message, state: FSMContext, db_user: User):
    await state.update_data(faq_new_q=message.text.strip())
    await state.set_state(FAQAdminStates.edit_answer)
    await message.answer(t(db_user.language, "faq.new_answer"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(FAQAdminStates.edit_answer), F.text
)
async def faq_edit_a(message: Message, state: FSMContext, db_user: User, session):
    lang = db_user.language
    data = await state.get_data()
    fid = data["faq_edit_id"]
    ok = await FAQService(session).update_qa(
        fid,
        question_uz=data["faq_new_q"],
        answer_uz=message.text.strip(),
    )
    await state.clear()
    await message.answer(
        t(lang, "faq.saved") if ok else t(lang, "errors.generic"),
        reply_markup=main_menu_kb(lang, db_user),
    )


# --- Delete FAQ ---
@router.callback_query(F.data == "faqadm:delfaq", IsAdmin())
async def faqadm_delfaq(query: CallbackQuery, db_user: User, session, state: FSMContext):
    lang = db_user.language
    cats = await FAQCategoryService(session).list_active_ordered()
    if not cats:
        await query.answer(t(lang, "faq.no_categories"), show_alert=True)
        return
    await state.set_state(FAQAdminStates.delete_pick_category)
    await query.message.answer(
        t(lang, "faq.pick_category_delete_faq"), reply_markup=_cat_rows(cats, lang, "faqadm:dcat")
    )
    await query.answer()


@router.callback_query(
    F.data.startswith("faqadm:dcat:"), IsAdmin(), StateFilter(FAQAdminStates.delete_pick_category)
)
async def faqadm_dcat(query: CallbackQuery, state: FSMContext, db_user: User, session):
    lang = db_user.language
    try:
        cid = int(query.data.split(":")[-1])
    except (IndexError, ValueError):
        await query.answer()
        return
    faqs = await FAQService(session).list_by_category_ordered(cid)
    if not faqs:
        await query.answer(t(lang, "faq.empty_category"), show_alert=True)
        return
    await state.set_state(FAQAdminStates.delete_pick)
    await query.message.answer(
        t(lang, "faq.pick_to_delete"), reply_markup=_faq_rows_del(faqs, lang)
    )
    await query.answer()


def _faq_rows_del(faqs: list, lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for f in faqs:
        title = f.question_ru if lang == "ru" and f.question_ru else f.question_uz
        rows.append([InlineKeyboardButton(text=title[:64], callback_data=f"faqd:{f.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(
    F.data.startswith("faqd:"), IsAdmin(), StateFilter(FAQAdminStates.delete_pick)
)
async def faq_delete_do(query: CallbackQuery, state: FSMContext, db_user: User, session):
    lang = db_user.language
    try:
        fid = int(query.data.split(":", 1)[1])
    except ValueError:
        await query.answer()
        return
    ok = await FAQService(session).delete(fid)
    await state.clear()
    await query.message.answer(
        t(lang, "faq.deleted") if ok else t(lang, "errors.generic"),
        reply_markup=main_menu_kb(lang, db_user),
    )
    await query.answer()
