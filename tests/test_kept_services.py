from datetime import timedelta

from app.services import audit_service
from app.services.admin_service import is_bot_admin
from app.services.broadcast_service import parse_inline_buttons
from app.services.dynamic_keyboard import (
    get_dynamic_inline_keyboard,
    get_dynamic_keyboard,
    get_dynamic_reply_keyboard,
)
from app.services.event_service import EventService
from app.services.faq_category_service import FAQCategoryService
from app.services.faq_service import FAQService
from app.services.group_service import GroupService
from app.services.project_service import ProjectService
from app.services.region_service import RegionService
from app.services.suggestion_service import SuggestionService
from app.services.ticket_service import TicketService
from app.services.user_service import UserService
from app.utils.timefmt import now_utc


async def test_region_service_crud_and_resolve(session):
    svc = RegionService(session)
    r = await svc.create("Toshkent", "Ташкент")
    assert (await svc.list_active_ordered())[0].id == r.id
    assert await svc.update_names(r.id, name_ru="Ташкент!")
    assert (await svc.get(r.id)).name_ru == "Ташкент!"
    assert (await svc.resolve_by_label("Toshkent", "uz")).id == r.id
    assert await svc.resolve_by_label("", "uz") is None
    assert await svc.set_active(r.id, False)
    assert await svc.resolve_by_label("Toshkent", "uz") is None
    assert len(await svc.list_all_ordered()) == 1


async def test_faq_services(session):
    cat = await FAQCategoryService(session).create("Umumiy", "Общее")
    assert (await FAQCategoryService(session).get(cat.id)).name_uz == "Umumiy"
    assert await FAQCategoryService(session).update_names(cat.id, name_uz="U2")
    faq = await FAQService(session).create(cat.id, "q-uz", "a-uz", "q-ru", "a-ru")
    assert (await FAQService(session).list_by_category_ordered(cat.id))[0].id == faq.id
    assert await FAQService(session).update_qa(faq.id, answer_uz="a2")
    assert (await FAQService(session).get(faq.id)).answer_uz == "a2"
    assert await FAQService(session).delete(faq.id)
    assert not await FAQService(session).update_qa(9999, answer_uz="x")
    assert await FAQCategoryService(session).set_active(cat.id, False)
    assert await FAQCategoryService(session).list_active_ordered() == []


async def test_project_service(session):
    svc = ProjectService(session)
    p = await svc.create("Title", "Desc")
    assert (await svc.get(p.id)).title == "Title"
    assert (await svc.list_active())[0].id == p.id


async def test_group_service_upsert(session):
    svc = GroupService(session)
    g1 = await svc.upsert_link(-100, "Proj", "desc")
    g2 = await svc.upsert_link(-100, "Proj2", None)
    assert g1.id == g2.id and g2.project_name == "Proj2"
    assert (await svc.get_by_chat_id(-100)).project_name == "Proj2"


async def test_suggestion_and_ticket_services(session, make_user):
    user = await make_user()
    s = await SuggestionService(session).create(user, "idea")
    await SuggestionService(session).set_admin_message_id(s.id, 42)

    ts = TicketService(session)
    ticket = await ts.create(user, "help me")
    assert (await ts.get(ticket.id)).body_text == "help me"
    await ts.add_admin_message(ticket.id, "reply", telegram_message_id=7)
    await ts.set_admin_delivery(ticket.id, message_id=99, thread_id=3)
    assert (await ts.get_by_admin_root_message(99)).id == ticket.id
    assert await ts.mark_in_progress(ticket.id)
    assert await ts.close(ticket.id)
    assert (await ts.get(ticket.id)).status == "closed"
    assert (await ts.load_user(ticket)).id == user.id


async def test_user_service(session, make_user):
    region = await RegionService(session).create("R", "Р")
    svc = UserService(session)
    u = await svc.create_user(12345, "Ali", region.id, age=20, language="ru", phone="998901112233")
    assert u.role == "user"
    assert await svc.set_role(12345, "admin")
    assert (await svc.get_by_telegram_id(12345)).role == "admin"
    assert not await svc.set_role(99999, "admin")
    await svc.set_language(12345, "uz")
    assert await svc.count_users() == 1
    assert await svc.count_active_users(7) == 1
    users, pages = await svc.list_users_page(query="Ali")
    assert len(users) == 1 and pages == 1
    assert 12345 in await svc.all_telegram_ids()
    # role escalation never demotes
    u.role = "super_admin"
    await session.flush()
    await svc.ensure_env_roles(u)
    assert u.role == "super_admin"


async def test_dynamic_keyboards(session):
    assert await get_dynamic_reply_keyboard(session, kind="regions", language="uz") is None
    await RegionService(session).create("Toshkent", "Ташкент")
    kb = await get_dynamic_reply_keyboard(session, kind="regions", language="ru")
    assert kb and kb.keyboard[0][0].text == "Ташкент"
    assert await get_dynamic_keyboard(session, "regions", "uz") is not None
    assert await get_dynamic_keyboard(session, "unknown", "uz") is None

    assert (
        await get_dynamic_inline_keyboard(
            session, kind="faq_categories", language="uz", callback_prefix="ufaq"
        )
        is None
    )
    cat = await FAQCategoryService(session).create("Umumiy", "Общее")
    ckb = await get_dynamic_inline_keyboard(
        session, kind="faq_categories", language="uz", callback_prefix="ufaq"
    )
    assert ckb and ckb.inline_keyboard[0][0].callback_data == f"ufaq:c:{cat.id}"
    await FAQService(session).create(cat.id, "q", "a", None, None)
    fkb = await get_dynamic_inline_keyboard(
        session, kind="faqs_in_category", language="uz", callback_prefix="ufaq", category_id=cat.id
    )
    assert fkb and ":q:" in fkb.inline_keyboard[0][0].callback_data


def test_parse_inline_buttons():
    assert parse_inline_buttons(None) is None
    assert parse_inline_buttons("nourl line") is None
    kb = parse_inline_buttons("Open|https://example.com\nBad|http://x\nGarbage")
    assert kb and len(kb.inline_keyboard) == 1  # only the https button survives


def test_is_bot_admin(make_user):
    from app.database.models import User

    assert not is_bot_admin(None)
    assert is_bot_admin(User(telegram_id=1, full_name="a", role="admin"))
    assert not is_bot_admin(User(telegram_id=1, full_name="a", role="user"))


async def test_event_service_edits(session, make_user, make_event):
    admin = await make_user(role="admin")
    svc = EventService(session)
    starts = now_utc() + timedelta(hours=2)
    ev, err = await svc.create(
        admin_user_id=admin.id,
        title="X",
        description="d",
        location="L",
        region_id=None,
        tz="UTC",
        starts_at=starts,
        ends_at=starts + timedelta(hours=2),
        capacity=3,
    )
    assert ev and not err
    # bad inputs
    _, e1 = await svc.create(
        admin_user_id=admin.id,
        title="X",
        description="",
        location="",
        region_id=None,
        tz="Bad/Zone",
        starts_at=starts,
        ends_at=starts + timedelta(hours=1),
        capacity=1,
    )
    assert e1 == "shifts.bad_tz"

    ev2, err = await svc.set_text_field(ev.id, "title", "New")
    assert ev2.title == "New" and not err
    _, err = await svc.set_capacity(ev.id, 0)
    assert err == "admin_events.bad_capacity"
    ev3, err = await svc.set_capacity(ev.id, 10)
    assert ev3.capacity == 10 and not err
    ev4, err = await svc.set_times(ev.id, starts, starts + timedelta(hours=4))
    assert ev4 and not err
    closed, err = await svc.close(ev.id)
    assert closed.status == "closed" and not err


async def test_capacity_below_signups_rejected(session, make_user, make_event):
    from app.services.signup_service import SignupService

    u = await make_user()
    event = await make_event(capacity=1)
    await SignupService(session).sign_up(u, event.id)
    _, err = await EventService(session).set_capacity(event.id, 0)
    assert err in ("admin_events.bad_capacity", "admin_events.capacity_below_signups")
    # capacity below current signups
    event2 = await make_event(capacity=2)
    await SignupService(session).sign_up(await make_user(), event2.id)
    await SignupService(session).sign_up(await make_user(), event2.id)
    _, err = await EventService(session).set_capacity(event2.id, 1)
    assert err == "admin_events.capacity_below_signups"


async def test_audit_record(session, make_user):
    admin = await make_user(role="admin")
    await audit_service.record(
        session,
        actor_telegram_id=admin.telegram_id,
        action="test_action",
        target_type="user",
        target_id=42,
        summary="hello",
    )
    from app.database.models import AuditLog
    from sqlalchemy import select

    rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1 and rows[0].action == "test_action"
