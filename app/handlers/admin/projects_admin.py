from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.database.models import User
from app.handlers.filters import IsAdmin
from app.handlers.labels import label_set
from app.i18n import t
from app.keyboards.common import main_menu_kb, remove_kb
from app.services.project_service import ProjectService
from app.states.forms import AdminProjectStates

router = Router(name="admin_projects")


@router.message(
    F.chat.type == "private",
    IsAdmin(),
    StateFilter(None),
    F.text.in_(label_set("menu.projects_admin")),
)
async def start_add_project(message: Message, state: FSMContext, db_user: User):
    lang = db_user.language
    await state.set_state(AdminProjectStates.title)
    await message.answer(
        t(lang, "admin_projects.start"), parse_mode="HTML", reply_markup=remove_kb()
    )


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(AdminProjectStates.title), Command("cancel")
)
async def cancel_title(message: Message, state: FSMContext, db_user: User):
    lang = db_user.language
    await state.clear()
    await message.answer(t(lang, "admin_projects.cancel"), reply_markup=main_menu_kb(lang, db_user))


@router.message(F.chat.type == "private", IsAdmin(), StateFilter(AdminProjectStates.title), F.text)
async def project_title(message: Message, state: FSMContext, db_user: User):
    lang = db_user.language
    title = (message.text or "").strip()
    if len(title) < 2:
        await message.answer(t(lang, "admin_projects.start"), parse_mode="HTML")
        return
    await state.update_data(title=title)
    await state.set_state(AdminProjectStates.description)
    await message.answer(t(lang, "admin_projects.ask_desc"))


@router.message(
    F.chat.type == "private",
    IsAdmin(),
    StateFilter(AdminProjectStates.description),
    Command("cancel"),
)
async def cancel_desc(message: Message, state: FSMContext, db_user: User):
    lang = db_user.language
    await state.clear()
    await message.answer(t(lang, "admin_projects.cancel"), reply_markup=main_menu_kb(lang, db_user))


@router.message(
    F.chat.type == "private", IsAdmin(), StateFilter(AdminProjectStates.description), F.text
)
async def project_description(message: Message, state: FSMContext, db_user: User, session):
    lang = db_user.language
    desc = (message.text or "").strip()
    if len(desc) < 3:
        await message.answer(t(lang, "admin_projects.ask_desc"))
        return
    data = await state.get_data()
    title = data.get("title") or ""
    await state.clear()
    await ProjectService(session).create(title, desc)
    await message.answer(
        t(lang, "admin_projects.saved", title=title), reply_markup=main_menu_kb(lang, db_user)
    )
