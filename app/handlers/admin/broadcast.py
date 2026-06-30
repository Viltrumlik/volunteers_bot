import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.config import get_settings
from app.database.models import User
from app.handlers.filters import IsAdmin
from app.handlers.labels import label_set
from app.i18n import t
from app.keyboards.common import main_menu_kb
from app.repositories.news_repository import NewsRepository
from app.services.news_dispatch_service import enqueue_news_job, process_news_broadcast_safe
from app.states.forms import BroadcastStates

logger = logging.getLogger(__name__)
router = Router(name="broadcast")


@router.message(
    F.chat.type == "private",
    IsAdmin(),
    StateFilter(None),
    F.text.in_(label_set("menu.broadcast")),
)
async def broadcast_start(message: Message, state: FSMContext, db_user: User):
    await state.set_state(BroadcastStates.content)
    await message.answer(t(db_user.language, "broadcast.send_text"))


@router.message(
    F.chat.type == "private",
    IsAdmin(),
    StateFilter(BroadcastStates.content),
    F.photo,
)
async def broadcast_photo(message: Message, state: FSMContext, db_user: User):
    await state.update_data(photo_file_id=message.photo[-1].file_id, text=message.caption)
    await state.set_state(BroadcastStates.buttons)
    await message.answer(t(db_user.language, "broadcast.buttons_prompt"))


@router.message(F.chat.type == "private", IsAdmin(), StateFilter(BroadcastStates.content), F.text)
async def broadcast_text(message: Message, state: FSMContext, db_user: User):
    await state.update_data(photo_file_id=None, text=message.text)
    await state.set_state(BroadcastStates.buttons)
    await message.answer(t(db_user.language, "broadcast.buttons_prompt"))


@router.message(F.chat.type == "private", IsAdmin(), StateFilter(BroadcastStates.buttons), F.text)
async def broadcast_buttons(message: Message, state: FSMContext, db_user: User):
    raw = (message.text or "").strip()
    if raw == "/skip":
        await state.update_data(buttons_raw=None)
    else:
        await state.update_data(buttons_raw=raw)
    await state.set_state(BroadcastStates.confirm)
    await message.answer(t(db_user.language, "broadcast.confirm"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(BroadcastStates.confirm), Command("cancel")
)
async def broadcast_cancel(message: Message, state: FSMContext, db_user: User):
    lang = db_user.language
    await state.clear()
    await message.answer(t(lang, "broadcast.cancelled"), reply_markup=main_menu_kb(lang, db_user))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(BroadcastStates.confirm), Command("yes")
)
async def broadcast_run(
    message: Message,
    state: FSMContext,
    db_user: User,
    session,
    bot,
    after_commit_tasks: list,
):
    lang = db_user.language
    payload = await state.get_data()
    await state.clear()
    nrepo = NewsRepository(session)
    news = await nrepo.create_pending(
        created_by_telegram_id=db_user.telegram_id,
        text=payload.get("text"),
        photo_file_id=payload.get("photo_file_id"),
        buttons_raw=payload.get("buttons_raw"),
    )
    await session.flush()
    news_id = news.id
    settings = get_settings()
    use_redis = bool((settings.redis_url or "").strip())

    async def after_commit():
        if use_redis:
            await enqueue_news_job(news_id)
            return
        ok, fail = await process_news_broadcast_safe(bot, news_id)
        await message.answer(
            t(lang, "broadcast.done", ok=ok, fail=fail),
            reply_markup=main_menu_kb(lang, db_user),
        )
        logger.info("Broadcast finished ok=%s fail=%s by %s", ok, fail, db_user.telegram_id)

    after_commit_tasks.append(after_commit())
    if use_redis:
        await message.answer(t(lang, "broadcast.queued"), reply_markup=main_menu_kb(lang, db_user))
    else:
        await message.answer(t(lang, "broadcast.started"))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(BroadcastStates.content), F.document
)
async def broadcast_doc_fallback(message: Message, db_user: User):
    await message.answer(t(db_user.language, "broadcast.send_photo"))
