import html

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.types import Message

from app.database.models import Gender, User
from app.handlers.filters import IsRegistered
from app.handlers.labels import label_set
from app.i18n import t
from app.keyboards.common import main_menu_kb
from app.services.application_service import ApplicationService
from app.services.region_service import RegionService

router = Router(name="user_profile")


def _gender_display(lang: str, raw: str | None) -> str:
    if not raw:
        return "—"
    mapping = {
        Gender.female.value: t(lang, "gender.female_btn"),
        Gender.male.value: t(lang, "gender.male_btn"),
        Gender.other.value: t(lang, "gender.other_btn"),
        Gender.unspecified.value: t(lang, "gender.unspecified_btn"),
    }
    return mapping.get(raw, raw)


@router.message(
    F.chat.type == "private",
    IsRegistered(),
    StateFilter(None),
    F.text.in_(label_set("menu.profile")),
)
async def show_profile(message: Message, db_user: User, session):
    lang = db_user.language
    rsvc = RegionService(session)
    region_name = "—"
    if db_user.region_id:
        reg = await rsvc.get(db_user.region_id)
        if reg:
            region_name = reg.name_ru if lang == "ru" else reg.name_uz

    lines = [
        f"<b>{t(lang, 'profile.title')}</b>",
        t(lang, "profile.line_name", name=html.escape(db_user.full_name)),
        t(
            lang,
            "profile.line_age",
            age=db_user.age if db_user.age is not None else "—",
        ),
        t(lang, "profile.line_region", region=html.escape(region_name)),
        t(lang, "profile.line_gender", gender=html.escape(_gender_display(lang, db_user.gender))),
        t(
            lang,
            "profile.line_bio",
            bio=html.escape(db_user.bio) if db_user.bio else "—",
        ),
    ]
    appsvc = ApplicationService(session)
    joined = await appsvc.list_for_profile(db_user.id)
    if joined:
        lines.append("")
        lines.append(t(lang, "profile.joined_title"))
        for a in joined:
            lines.append(f"• {html.escape(a.project.title)}")
    else:
        lines.append("")
        lines.append(t(lang, "profile.joined_empty"))

    text = "\n".join(lines)
    if db_user.photo_file_id:
        await message.answer_photo(db_user.photo_file_id, caption=text, parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, parse_mode=ParseMode.HTML)
    await message.answer(t(lang, "common.menu_hint"), reply_markup=main_menu_kb(lang, db_user))
