import html
import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.models import User
from app.handlers.filters import IsAdmin
from app.handlers.labels import label_set
from app.i18n import t
from app.keyboards.common import main_menu_kb
from app.services.application_service import ApplicationService

logger = logging.getLogger(__name__)
router = Router(name="admin_applications")


def _apps_kb(lang: str, apps: list) -> InlineKeyboardMarkup | None:
    if not apps:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for a in apps[:25]:
        rows.append(
            [
                InlineKeyboardButton(text=f"✅ #{a.id}", callback_data=f"apm:y:{a.id}"),
                InlineKeyboardButton(text=f"❌ #{a.id}", callback_data=f"apm:n:{a.id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="apm:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(
    F.chat.type == "private",
    IsAdmin(),
    StateFilter(None),
    F.text.in_(label_set("menu.applications_admin")),
)
async def open_applications(message: Message, db_user: User, session):
    lang = db_user.language
    pending = await ApplicationService(session).list_pending()
    if not pending:
        await message.answer(t(lang, "admin_apps.empty"), reply_markup=main_menu_kb(lang, db_user))
        return
    lines = [t(lang, "admin_apps.title")]
    for a in pending:
        uname = a.user.full_name if a.user else "?"
        pname = a.project.title if a.project else "?"
        lines.append(
            t(lang, "admin_apps.line", id=a.id, user=html.escape(uname), project=html.escape(pname))
        )
    kb = _apps_kb(lang, pending)
    await message.answer(
        "\n".join(lines),
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("apm:"))
async def applications_callback(query: CallbackQuery, db_user: User | None, session):
    if not db_user or not query.message:
        await query.answer()
        return
    lang = db_user.language
    data = query.data or ""
    if data == "apm:close":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.answer()
        await query.message.answer(
            t(lang, "common.menu_hint"), reply_markup=main_menu_kb(lang, db_user)
        )
        return
    parts = data.split(":")
    if len(parts) != 3 or parts[1] not in ("y", "n"):
        await query.answer()
        return
    try:
        app_id = int(parts[2])
    except ValueError:
        await query.answer()
        return
    asvc = ApplicationService(session)
    approve = parts[1] == "y"
    ok, err_key = await asvc.approve_or_reject(app_id, approve=approve)
    if not ok:
        await query.answer(t(lang, err_key), show_alert=True)
        return
    await query.answer()
    if approve:
        await query.message.reply(t(lang, "admin_apps.approved", id=app_id))
    else:
        await query.message.reply(t(lang, "admin_apps.rejected", id=app_id))

    pending = await asvc.list_pending()
    kb = _apps_kb(lang, pending)
    if kb is None:
        await query.message.edit_text(t(lang, "admin_apps.empty"))
    else:
        lines = [t(lang, "admin_apps.title")]
        for a in pending:
            uname = a.user.full_name if a.user else "?"
            pname = a.project.title if a.project else "?"
            lines.append(
                t(
                    lang,
                    "admin_apps.line",
                    id=a.id,
                    user=html.escape(uname),
                    project=html.escape(pname),
                )
            )
        await query.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML)
