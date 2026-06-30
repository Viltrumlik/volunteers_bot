import html

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.models import User
from app.handlers.filters import IsAdmin, IsRegistered
from app.i18n import other_lang, t
from app.keyboards.common import faq_admin_root_inline, main_menu_kb
from app.services.dynamic_keyboard import get_dynamic_inline_keyboard
from app.services.faq_category_service import FAQCategoryService
from app.services.faq_service import FAQService
from app.services.user_service import UserService

router = Router(name="menu")


def _labels(key: str) -> set[str]:
    return {t("uz", key), t("ru", key)}


async def _toggle_language(message: Message, db_user: User, session) -> None:
    new_lang = other_lang(db_user.language)
    await UserService(session).set_language(db_user.telegram_id, new_lang)
    await session.refresh(db_user)
    await message.answer(
        t(new_lang, "language.changed"), reply_markup=main_menu_kb(new_lang, db_user)
    )


@router.message(F.chat.type == "private", IsRegistered(), StateFilter(None), Command("language"))
async def cmd_language(message: Message, db_user: User, session):
    await _toggle_language(message, db_user, session)


@router.message(F.chat.type == "private", IsRegistered(), StateFilter(None), Command("lang"))
async def cmd_lang(message: Message, db_user: User, session):
    await _toggle_language(message, db_user, session)


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    StateFilter(None),
    F.text.in_(_labels("menu.faq_admin")),
    IsAdmin(),
)
async def open_faq_admin_panel(message: Message, db_user: User):
    lang = db_user.language
    await message.answer(t(lang, "faq.admin_title"), reply_markup=faq_admin_root_inline(lang))


@router.message(
    F.chat.type == "private", IsRegistered(), StateFilter(None), F.text.in_(_labels("menu.faq"))
)
async def open_faq(message: Message, db_user: User, session):
    lang = db_user.language
    kb = await get_dynamic_inline_keyboard(
        session, kind="faq_categories", language=lang, callback_prefix="ufaq"
    )
    if kb is None:
        await message.answer(t(lang, "faq.no_categories"), reply_markup=main_menu_kb(lang, db_user))
        return
    extra = [[InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="ufaq:close")]]
    rows = kb.inline_keyboard + extra
    await message.answer(
        t(lang, "faq.pick_category"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


@router.callback_query(F.data.startswith("ufaq:"))
async def ufaq_callback(query: CallbackQuery, db_user: User | None, session):
    if not db_user:
        await query.answer()
        return
    lang = db_user.language
    data = query.data or ""
    if data == "ufaq:close":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.answer()
        await query.message.answer(
            t(lang, "common.menu_hint"), reply_markup=main_menu_kb(lang, db_user)
        )
        return
    if data == "ufaq:root":
        kb = await get_dynamic_inline_keyboard(
            session, kind="faq_categories", language=lang, callback_prefix="ufaq"
        )
        if not kb:
            await query.answer(t(lang, "faq.no_categories"), show_alert=True)
            return
        extra = [
            [InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="ufaq:close")]
        ]
        await query.message.edit_text(
            t(lang, "faq.pick_category"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + extra),
        )
        await query.answer()
        return
    if data.startswith("ufaq:c:"):
        try:
            cid = int(data.split(":")[2])
        except (IndexError, ValueError):
            await query.answer()
            return
        cat = await FAQCategoryService(session).get(cid)
        if not cat or not cat.is_active:
            await query.answer()
            return
        faq_kb = await get_dynamic_inline_keyboard(
            session,
            kind="faqs_in_category",
            language=lang,
            callback_prefix="ufaq",
            category_id=cid,
        )
        if not faq_kb:
            await query.answer(t(lang, "faq.empty_category"), show_alert=True)
            return
        nav = [
            InlineKeyboardButton(text=t(lang, "common.back"), callback_data="ufaq:root"),
            InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="ufaq:close"),
        ]
        rows = [*faq_kb.inline_keyboard, nav]
        await query.message.edit_text(
            t(lang, "faq.pick_in_category", name=_label_cat(cat, lang)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        await query.answer()
        return
    if data.startswith("ufaq:q:"):
        try:
            fid = int(data.split(":")[2])
        except (IndexError, ValueError):
            await query.answer()
            return
        faq = await FAQService(session).get(fid)
        if not faq:
            await query.answer()
            return
        q = faq.question_ru if lang == "ru" and faq.question_ru else faq.question_uz
        a = faq.answer_ru if lang == "ru" and faq.answer_ru else faq.answer_uz
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(lang, "common.back"), callback_data=f"ufaq:c:{faq.category_id}"
                    ),
                    InlineKeyboardButton(
                        text=t(lang, "common.back_menu"), callback_data="ufaq:close"
                    ),
                ]
            ]
        )
        await query.message.edit_text(f"<b>{html.escape(q)}</b>\n\n{a}", reply_markup=kb)
        await query.answer()
        return
    await query.answer()


def _label_cat(cat, lang: str) -> str:
    return (cat.name_ru if lang == "ru" else cat.name_uz) or cat.name_uz


@router.message(
    F.chat.type == "private", IsRegistered(), StateFilter(None), F.text.in_(_labels("menu.stats"))
)
async def stats(message: Message, db_user: User, session):
    lang = db_user.language
    svc = UserService(session)
    total = await svc.count_users()
    active = await svc.count_active_users(7)
    text = "\n".join(
        [
            t(lang, "stats.title"),
            t(lang, "stats.total", total=total),
            t(lang, "stats.active", active=active),
        ]
    )
    await message.answer(text, reply_markup=main_menu_kb(lang, db_user))


@router.message(F.chat.type == "private", ~IsRegistered(), StateFilter(None), F.text)
async def need_register(message: Message):
    fu = message.from_user
    lc = (fu.language_code if fu else None) or "uz"
    lang = "ru" if lc.lower().startswith("ru") else "uz"
    await message.answer(t(lang, "errors.need_register"))
