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
from app.integrations.google_sheets_service import enqueue_log_ticket
from app.keyboards.common import main_menu_kb
from app.monitoring.metrics import incr, incr_daily_counter
from app.services.ticket_service import TicketService
from app.states.forms import SupportStates
from app.utils.formatting import format_ticket_header
from app.utils.sanitize import strip_invisible
from app.utils.telegram_user import effective_telegram_user

logger = logging.getLogger(__name__)
router = Router(name="support")

MAX_USER_MEDIA_BYTES = 10 * 1024 * 1024


async def _after_ticket_created(ticket, db_user) -> None:
    label = f"{db_user.full_name} ({db_user.telegram_id})"
    await enqueue_log_ticket(ticket, label)
    await incr("tickets_created")
    await incr_daily_counter("tickets_day")


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    StateFilter(None),
    F.text.in_(label_set("menu.support")),
)
async def support_entry(message: Message, state: FSMContext, db_user: User):
    await state.set_state(SupportStates.message)
    await message.answer(
        t(db_user.language, "support.prompt"),
        reply_markup=main_menu_kb(db_user.language, db_user),
    )


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    StateFilter(SupportStates.message),
    F.text.startswith("/"),
)
async def support_ignore_commands(message: Message, db_user: User):
    await message.answer(t(db_user.language, "support.prompt"))


@router.message(
    F.chat.type == "private", IsRegistered(), StateFilter(SupportStates.message), F.text
)
async def support_text(message: Message, state: FSMContext, db_user: User, session, bot, tg_user):
    settings = get_settings()
    lang = db_user.language
    sender = effective_telegram_user(message, tg_user)
    if sender is None:
        await message.answer(t(lang, "errors.generic"))
        return
    body = strip_invisible((message.text or "").strip())[:4096]
    if body in all_registered_menu_labels():
        await state.clear()
        await message.answer(t(lang, "common.menu_hint"), reply_markup=main_menu_kb(lang, db_user))
        return
    if not await try_acquire("ticket", sender.id, settings.creation_cooldown_sec):
        await message.answer(t(lang, "errors.cooldown"))
        return
    ts = TicketService(session)
    ticket = await ts.create(db_user, body)
    await session.flush()
    await _after_ticket_created(ticket, db_user)
    header = format_ticket_header(ticket.id, db_user, sender.username)
    full = header + html.escape(body)
    try:
        thread = settings.admin_ticket_topic_id
        sent = await bot.send_message(
            settings.admin_group_id,
            full,
            parse_mode="HTML",
            message_thread_id=thread,
        )
        await ts.set_admin_delivery(ticket.id, message_id=sent.message_id, thread_id=thread)
    except Exception as e:
        logger.exception("Forward ticket to admin group: %s", e)
        await message.answer(t(lang, "errors.generic"))
        return
    await state.clear()
    await message.answer(t(lang, "support.sent"), reply_markup=main_menu_kb(lang, db_user))


@router.message(
    F.chat.type == "private", IsRegistered(), StateFilter(SupportStates.message), F.photo
)
async def support_photo(message: Message, state: FSMContext, db_user: User, session, bot, tg_user):
    settings = get_settings()
    lang = db_user.language
    sender = effective_telegram_user(message, tg_user)
    if sender is None:
        await message.answer(t(lang, "errors.generic"))
        return
    if not await try_acquire("ticket", sender.id, settings.creation_cooldown_sec):
        await message.answer(t(lang, "errors.cooldown"))
        return
    ph = message.photo[-1] if message.photo else None
    if ph and getattr(ph, "file_size", None) and ph.file_size > MAX_USER_MEDIA_BYTES:
        await message.answer(t(lang, "errors.generic"))
        return
    cap = strip_invisible((message.caption or "[photo]").strip())[:1024]
    ts = TicketService(session)
    ticket = await ts.create(db_user, cap)
    await session.flush()
    await _after_ticket_created(ticket, db_user)
    header = format_ticket_header(ticket.id, db_user, sender.username)
    caption = header + html.escape(cap)
    try:
        thread = settings.admin_ticket_topic_id
        sent = await bot.send_photo(
            settings.admin_group_id,
            message.photo[-1].file_id,
            caption=caption[:1024],
            parse_mode="HTML",
            message_thread_id=thread,
        )
        await ts.set_admin_delivery(ticket.id, message_id=sent.message_id, thread_id=thread)
    except Exception as e:
        logger.exception("Forward ticket photo: %s", e)
        await message.answer(t(lang, "errors.generic"))
        return
    await state.clear()
    await message.answer(t(lang, "support.sent"), reply_markup=main_menu_kb(lang, db_user))


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    StateFilter(SupportStates.message),
    ~F.text,
    ~F.photo,
)
async def support_other_media(
    message: Message, state: FSMContext, db_user: User, session, bot, tg_user
):
    settings = get_settings()
    lang = db_user.language
    sender = effective_telegram_user(message, tg_user)
    if sender is None:
        await message.answer(t(lang, "errors.generic"))
        return
    if not await try_acquire("ticket", sender.id, settings.creation_cooldown_sec):
        await message.answer(t(lang, "errors.cooldown"))
        return
    cap = strip_invisible((message.caption or "").strip() or f"[{message.content_type}]")[:4096]
    ts = TicketService(session)
    ticket = await ts.create(db_user, cap)
    await session.flush()
    await _after_ticket_created(ticket, db_user)
    header = format_ticket_header(ticket.id, db_user, sender.username)
    full_caption = (header + html.escape(cap))[:1024]
    try:
        thread = settings.admin_ticket_topic_id
        sent = await bot.copy_message(
            chat_id=settings.admin_group_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            caption=full_caption,
            parse_mode="HTML",
            message_thread_id=thread,
        )
        await ts.set_admin_delivery(ticket.id, message_id=sent.message_id, thread_id=thread)
    except Exception as e:
        logger.warning("copy_message ticket fallback to text: %s", e)
        try:
            thread = settings.admin_ticket_topic_id
            sent = await bot.send_message(
                settings.admin_group_id,
                header + html.escape(cap),
                parse_mode="HTML",
                message_thread_id=thread,
            )
            await ts.set_admin_delivery(ticket.id, message_id=sent.message_id, thread_id=thread)
        except Exception as e2:
            logger.exception("Forward ticket (fallback): %s", e2)
            await message.answer(t(lang, "errors.generic"))
            return
    await state.clear()
    await message.answer(t(lang, "support.sent"), reply_markup=main_menu_kb(lang, db_user))
