import logging

from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.database.models import Gender, User
from app.handlers.filters import may_use_admin_tools
from app.i18n import other_lang, t
from app.integrations.google_sheets_service import enqueue_add_user
from app.keyboards.common import (
    LANG_BTN_RU,
    LANG_BTN_UZ,
    LANG_PICK_LABELS,
    gender_reply_kb,
    language_pick_kb,
    main_menu_kb,
    registration_skip_age_kb,
    registration_skip_bio_kb,
    remove_kb,
)
from app.services.dynamic_keyboard import get_dynamic_keyboard
from app.services.region_service import RegionService
from app.services.user_service import UserService
from app.states.forms import RegistrationStates
from app.utils.telegram_user import effective_telegram_user
from app.utils.validation import validate_age_text, validate_bio

logger = logging.getLogger(__name__)
router = Router(name="registration")


async def _reply_no_regions(message: Message, lang: str, db_user: User | None) -> None:
    fu = message.from_user
    tid = fu.id if fu else None
    is_admin = tid is not None and may_use_admin_tools(tid, db_user)
    lines = [t(lang, "regions.none_available")]
    lines.append(
        t(lang, "regions.admin_hint_add_region") if is_admin else t(lang, "regions.user_try_later")
    )
    await message.answer("\n\n".join(lines), reply_markup=remove_kb())


def _is_skip(text: str | None, lang: str) -> bool:
    if not text:
        return False
    return text.strip() in (t(lang, "common.skip"), t(other_lang(lang), "common.skip"))


def _gender_from_label(label: str, lang: str) -> str | None:
    mapping = [
        (t(lang, "gender.female_btn"), Gender.female.value),
        (t(other_lang(lang), "gender.female_btn"), Gender.female.value),
        (t(lang, "gender.male_btn"), Gender.male.value),
        (t(other_lang(lang), "gender.male_btn"), Gender.male.value),
        (t(lang, "gender.other_btn"), Gender.other.value),
        (t(other_lang(lang), "gender.other_btn"), Gender.other.value),
        (t(lang, "gender.unspecified_btn"), Gender.unspecified.value),
        (t(other_lang(lang), "gender.unspecified_btn"), Gender.unspecified.value),
    ]
    for btn, val in mapping:
        if label.strip() == btn:
            return val
    return None


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext, db_user: User | None):
    await state.clear()
    if db_user:
        lang = db_user.language
        await message.answer(
            t(lang, "start.welcome_back"), reply_markup=main_menu_kb(lang, db_user)
        )
        return
    await state.set_state(RegistrationStates.language)
    await message.answer(t("uz", "start.pick_language"), reply_markup=language_pick_kb())


@router.message(StateFilter(RegistrationStates.language), F.chat.type == "private", F.text)
async def reg_language(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == LANG_BTN_UZ:
        lang = "uz"
    elif text == LANG_BTN_RU:
        lang = "ru"
    else:
        await message.answer(t("uz", "start.pick_language_retry"), reply_markup=language_pick_kb())
        return
    await state.update_data(lang=lang)
    await state.set_state(RegistrationStates.full_name)
    await message.answer(t(lang, "start.welcome"), reply_markup=remove_kb())


@router.message(StateFilter(RegistrationStates.full_name), F.chat.type == "private", F.text)
async def reg_name(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 255:
        await message.answer(t(lang, "start.welcome"))
        return
    await state.update_data(full_name=name)
    await state.set_state(RegistrationStates.age)
    await message.answer(t(lang, "start.ask_age"), reply_markup=registration_skip_age_kb(lang))


@router.message(StateFilter(RegistrationStates.age), F.chat.type == "private", F.text)
async def reg_age(message: Message, state: FSMContext, session, db_user: User | None):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    text = message.text or ""
    if text.strip() in LANG_PICK_LABELS:
        await message.answer(t(lang, "start.ask_age"), reply_markup=registration_skip_age_kb(lang))
        return
    if _is_skip(text, lang):
        await state.update_data(age=None)
    else:
        age = validate_age_text(text)
        if age is None:
            await message.answer(
                t(lang, "start.ask_age"), reply_markup=registration_skip_age_kb(lang)
            )
            return
        await state.update_data(age=age)
    await state.set_state(RegistrationStates.region)
    kb = await get_dynamic_keyboard(session, "regions", lang)
    if kb is None:
        await _reply_no_regions(message, lang, db_user)
    else:
        await message.answer(t(lang, "start.pick_region"), reply_markup=kb)


@router.message(StateFilter(RegistrationStates.region), F.chat.type == "private", F.text)
async def reg_region(message: Message, state: FSMContext, session, tg_user, db_user: User | None):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    kb = await get_dynamic_keyboard(session, "regions", lang)
    if kb is None:
        await _reply_no_regions(message, lang, db_user)
        return
    if (message.text or "").strip() in LANG_PICK_LABELS:
        await message.answer(t(lang, "start.pick_region"), reply_markup=kb)
        return
    label = (message.text or "").strip()
    rsvc = RegionService(session)
    region = await rsvc.resolve_by_label(label, lang)
    if not region:
        await message.answer(t(lang, "regions.pick_valid"), reply_markup=kb)
        return
    await state.update_data(region_id=region.id)
    await state.set_state(RegistrationStates.gender)
    await message.answer(t(lang, "start.ask_gender"), reply_markup=gender_reply_kb(lang))


@router.message(StateFilter(RegistrationStates.gender), F.chat.type == "private", F.text)
async def reg_gender(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    g = _gender_from_label(message.text or "", lang)
    if not g:
        await message.answer(t(lang, "start.ask_gender"), reply_markup=gender_reply_kb(lang))
        return
    await state.update_data(gender=g)
    await state.set_state(RegistrationStates.bio)
    await message.answer(t(lang, "start.ask_bio"), reply_markup=registration_skip_bio_kb(lang))


@router.message(StateFilter(RegistrationStates.bio), F.chat.type == "private", F.text)
async def reg_bio(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    text = message.text or ""
    if text.strip() in LANG_PICK_LABELS:
        await message.answer(t(lang, "start.ask_bio"), reply_markup=registration_skip_bio_kb(lang))
        return
    if _is_skip(text, lang):
        await state.update_data(bio=None)
    else:
        if not text.strip():
            await message.answer(
                t(lang, "start.ask_bio"), reply_markup=registration_skip_bio_kb(lang)
            )
            return
        bio = validate_bio(text)
        if bio is None:
            await message.answer(
                t(lang, "start.bio_too_long"), reply_markup=registration_skip_bio_kb(lang)
            )
            return
        await state.update_data(bio=bio)
    await state.set_state(RegistrationStates.photo)
    await message.answer(t(lang, "start.ask_photo"), reply_markup=registration_skip_bio_kb(lang))


@router.message(StateFilter(RegistrationStates.photo), F.chat.type == "private", F.photo)
async def reg_photo(message: Message, state: FSMContext, session, tg_user):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    file_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo_file_id=file_id)
    await _finalize_registration(message, state, session, tg_user, lang)


@router.message(StateFilter(RegistrationStates.photo), F.chat.type == "private", F.text)
async def reg_photo_skip(message: Message, state: FSMContext, session, tg_user):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    if not _is_skip(message.text, lang):
        await message.answer(
            t(lang, "start.ask_photo"), reply_markup=registration_skip_bio_kb(lang)
        )
        return
    await state.update_data(photo_file_id=None)
    await _finalize_registration(message, state, session, tg_user, lang)


async def _finalize_registration(
    message: Message, state: FSMContext, session, tg_user, lang: str
) -> None:
    data = await state.get_data()
    actor = effective_telegram_user(message, tg_user)
    if actor is None:
        logger.warning("finalize_registration: missing from_user")
        await state.clear()
        await message.answer(t(lang, "errors.generic"))
        return
    region_id = data.get("region_id")
    if region_id is None:
        await state.clear()
        await message.answer(t(lang, "errors.generic"))
        return
    svc = UserService(session)
    user = await svc.create_user(
        telegram_id=actor.id,
        full_name=data["full_name"],
        region_id=region_id,
        age=data.get("age"),
        language=lang,
        username=actor.username,
        gender=data.get("gender"),
        bio=data.get("bio"),
        photo_file_id=data.get("photo_file_id"),
    )
    await session.flush()
    rsvc = RegionService(session)
    reg = await rsvc.get(region_id)
    region_label = ""
    if reg:
        region_label = reg.name_ru if lang == "ru" else reg.name_uz
    await enqueue_add_user(user, region_label=region_label)
    await state.clear()
    logger.info("Registered user telegram_id=%s", user.telegram_id)
    await message.answer(t(lang, "start.done"), reply_markup=main_menu_kb(lang, user))
