"""Direct repository coverage for news / ticket / application / user repos."""

from __future__ import annotations

from app.repositories.application_repository import ApplicationRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository


async def test_news_repository_lifecycle(session):
    repo = NewsRepository(session)
    news = await repo.create_pending(
        created_by_telegram_id=1, text="hi", photo_file_id=None, buttons_raw=None
    )
    assert (await repo.get(news.id)).status == "pending"
    await repo.mark_sending(news.id)
    await repo.mark_completed(news.id, 5, 2)
    await session.refresh(news)
    assert news.status == "completed" and news.sent_ok == 5 and news.sent_fail == 2

    n2 = await repo.create_pending(
        created_by_telegram_id=1, text="x", photo_file_id=None, buttons_raw=None
    )
    await repo.mark_failed(n2.id, "boom")
    await session.refresh(n2)
    assert n2.status == "failed" and n2.error_message == "boom"


async def test_ticket_repository_chain_and_assign(session, make_user):
    user = await make_user()
    repo = TicketRepository(session)
    ticket = await repo.create(user.id, "help")
    await repo.set_admin_delivery(ticket.id, message_id=500, thread_id=2)
    await repo.mark_first_response_if_needed(ticket.id)
    await repo.assign(ticket.id, 777)
    await session.refresh(ticket)
    assert ticket.assigned_telegram_id == 777 and ticket.first_response_at is not None
    # chain lookup picks the ticket whose root matches the earliest message id
    found = await repo.get_by_admin_message_chain([999, 500])
    assert found and found.id == ticket.id
    assert await repo.get_by_admin_message_chain([]) is None


async def test_application_repository_listings(session, make_user):
    from app.database.models import Project

    user = await make_user(role="user")
    p1 = Project(title="A", description="d", is_active=True)
    p2 = Project(title="B", description="d", is_active=True)
    session.add_all([p1, p2])
    await session.flush()
    repo = ApplicationRepository(session)
    a1 = await repo.create_pending(user.id, p1.id)
    a1.status = "approved"
    await repo.create_pending(user.id, p2.id)
    await session.flush()
    assert len(await repo.list_for_user(user.id)) == 2
    approved = await repo.list_approved_for_user(user.id)
    assert len(approved) == 1 and approved[0].project_id == p1.id
    assert len(await repo.list_pending_with_users()) == 1


async def test_user_repository_search_and_counts(session):
    repo = UserRepository(session)
    from app.database.models import User

    session.add(User(telegram_id=1, full_name="Alice", role="user", phone="998901112233"))
    session.add(User(telegram_id=2, full_name="Bob", role="volunteer"))
    await session.flush()
    assert await repo.count_users() == 2
    assert await repo.count_active_users(7) == 2
    users, pages = await repo.list_users_page(query="alice")
    assert len(users) == 1 and users[0].telegram_id == 1
    users, _ = await repo.list_users_page(query="99890")
    assert len(users) == 1
    assert set(await repo.all_telegram_ids()) == {1, 2}
    await repo.touch_activity(1, username="alice")
