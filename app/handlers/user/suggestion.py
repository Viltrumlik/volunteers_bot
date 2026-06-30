import html
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.config import get_settings
from app.database.models import User
from app.handlers.filters import IsRegistered
from app.handlers.labels import all_registered_menu_labels, label_set
from app.i18n import t
from app.infrastructure.cooldown import try_acquire
from app.keyboards.common import main_menu_kb
from app.services.suggestion_service import SuggestionService
from app.states.forms import SuggestionStates
from app.utils.formatting import format_suggestion_header
from app.utils.telegram_user import effective_telegram_user

logger = logging.getLogger(__name__)
router = Router(name="suggestion")


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    StateFilter(None),
    F.text.in_(label_set("menu.suggestion")),
)
async def suggestion_entry(message: Message, state: FSMContext, db_user: User):
    await state.set_state(SuggestionStates.text)
    await message.answer(
        t(db_user.language, "suggestion.prompt"),
        reply_markup=main_menu_kb(db_user.language, db_user),
    )


@router.message(
    F.chat.type == "private", IsRegistered(), StateFilter(SuggestionStates.text), F.text
)
async def suggestion_body(
    message: Message, state: FSMContext, db_user: User, session, bot, tg_user
):
    settings = get_settings()
    lang = db_user.language
    sender = effective_telegram_user(message, tg_user)
    if sender is None:
        await message.answer(t(lang, "errors.generic"))
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer(t(lang, "suggestion.prompt"))
        return
    if text in all_registered_menu_labels():
        await state.clear()
        await message.answer(t(lang, "common.menu_hint"), reply_markup=main_menu_kb(lang, db_user))
        return
    if not await try_acquire("suggestion", sender.id, settings.creation_cooldown_sec):
        await message.answer(t(lang, "errors.cooldown"))
        return
    svc = SuggestionService(session)
    s = await svc.create(db_user, text)
    await session.flush()
    header = format_suggestion_header(s.id, db_user, sender.username)
    full = header + html.escape(text)
    try:
        sent = await bot.send_message(settings.admin_group_id, full, parse_mode="HTML")
        await svc.set_admin_message_id(s.id, sent.message_id)
    except Exception as e:
        logger.exception("Forward suggestion: %s", e)
        await message.answer(t(lang, "errors.generic"))
        return
    await state.clear()
    await message.answer(t(lang, "suggestion.thanks"), reply_markup=main_menu_kb(lang, db_user))
