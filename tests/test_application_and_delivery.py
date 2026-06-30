"""Coverage for kept services: application apply/approve + idempotent news delivery."""

from __future__ import annotations

from app.database.models import Project
from app.repositories.news_delivery_repository import NewsDeliveryRepository
from app.services.application_service import ApplicationService


async def _project(session, *, active: bool = True) -> Project:
    p = Project(title="Help", description="desc", is_active=active)
    session.add(p)
    await session.flush()
    return p


async def test_apply_idempotent_and_promotion(session, make_user):
    user = await make_user(role="user")
    project = await _project(session)
    svc = ApplicationService(session)

    app, err = await svc.apply(user, project.id)
    assert app and not err and app.status == "pending"

    # re-apply while pending -> rejected with key
    _, err = await svc.apply(user, project.id)
    assert err == "projects.apply_pending"

    ok, err = await svc.approve_or_reject(app.id, approve=True)
    assert ok and not err
    await session.refresh(user)
    assert user.role == "volunteer"  # auto-promoted

    # double approve blocked
    ok, err = await svc.approve_or_reject(app.id, approve=True)
    assert not ok and err == "admin_apps.not_pending"


async def test_apply_inactive_project(session, make_user):
    user = await make_user(role="user")
    project = await _project(session, active=False)
    _, err = await ApplicationService(session).apply(user, project.id)
    assert err == "projects.inactive"


async def test_news_delivery_ensure_row_idempotent(session):
    from app.database.models import News

    news = News(created_by_telegram_id=1, text="hi", status="pending")
    session.add(news)
    await session.flush()
    repo = NewsDeliveryRepository(session)
    r1 = await repo.ensure_row(news.id, 555)
    r2 = await repo.ensure_row(news.id, 555)
    assert r1.id == r2.id
    await repo.mark_sent(r1.id)
    await session.refresh(r1)
    assert r1.status == "sent"
