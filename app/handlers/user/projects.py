import html

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.models import User
from app.handlers.filters import IsRegistered
from app.handlers.labels import label_set
from app.i18n import t
from app.integrations.google_sheets_service import enqueue_log_application
from app.keyboards.common import main_menu_kb
from app.services.application_service import ApplicationService
from app.services.project_service import ProjectService

router = Router(name="user_projects")


def _projects_root_kb(lang: str, project_ids: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for pid, title in project_ids:
        rows.append([InlineKeyboardButton(text=title[:60], callback_data=f"upj:p:{pid}")])
    rows.append([InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="upj:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _detail_kb(lang: str, project_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "projects.apply"), callback_data=f"upj:a:{project_id}"
                )
            ],
            [
                InlineKeyboardButton(text=t(lang, "common.back"), callback_data="upj:root"),
                InlineKeyboardButton(text=t(lang, "common.back_menu"), callback_data="upj:close"),
            ],
        ]
    )


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    StateFilter(None),
    F.text.in_(label_set("menu.projects")),
)
async def open_projects(message: Message, db_user: User, session):
    lang = db_user.language
    projects = await ProjectService(session).list_active()
    if not projects:
        await message.answer(t(lang, "projects.empty"), reply_markup=main_menu_kb(lang, db_user))
        return
    titles = [(p.id, p.title) for p in projects]
    await message.answer(
        t(lang, "projects.list_title"),
        reply_markup=_projects_root_kb(lang, titles),
    )


@router.callback_query(F.data.startswith("upj:"))
async def projects_callback(query: CallbackQuery, db_user: User | None, session):
    if not db_user or not query.message:
        await query.answer()
        return
    lang = db_user.language
    data = query.data or ""
    parts = data.split(":")
    if len(parts) < 2:
        await query.answer()
        return
    action = parts[1]
    if action == "close":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.answer()
        await query.message.answer(
            t(lang, "common.menu_hint"), reply_markup=main_menu_kb(lang, db_user)
        )
        return
    if action == "root":
        projects = await ProjectService(session).list_active()
        if not projects:
            await query.answer(t(lang, "projects.empty"), show_alert=True)
            return
        titles = [(p.id, p.title) for p in projects]
        await query.message.edit_reply_markup(reply_markup=_projects_root_kb(lang, titles))
        await query.answer()
        return
    if action == "p" and len(parts) >= 3:
        try:
            pid = int(parts[2])
        except ValueError:
            await query.answer()
            return
        p = await ProjectService(session).get(pid)
        if not p or not p.is_active:
            await query.answer(t(lang, "errors.generic"), show_alert=True)
            return
        text = t(
            lang,
            "projects.detail",
            title=html.escape(p.title),
            description=html.escape(p.description),
        )
        await query.message.edit_text(
            text,
            reply_markup=_detail_kb(lang, p.id),
            parse_mode=ParseMode.HTML,
        )
        await query.answer()
        return
    if action == "a" and len(parts) >= 3:
        try:
            pid = int(parts[2])
        except ValueError:
            await query.answer()
            return
        asvc = ApplicationService(session)
        app, err = await asvc.apply(db_user, pid)
        if err:
            await query.answer(t(lang, err), show_alert=True)
            return
        psvc = ProjectService(session)
        proj = await psvc.get(pid)
        pname = proj.title if proj else ""
        await enqueue_log_application(app, db_user.full_name, pname)
        await query.answer(t(lang, "projects.applied"), show_alert=True)
        return
    await query.answer()
