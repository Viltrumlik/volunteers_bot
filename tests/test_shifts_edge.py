"""Signup edge cases: cancel waitlisted, cancel-when-absent, re-signup reactivation."""

from __future__ import annotations

from app.repositories.signup_repository import SignupRepository
from app.services.signup_service import SignupService


async def test_cancel_when_not_registered(session, make_user, make_event):
    u = await make_user()
    event = await make_event(capacity=2)
    ok, err, promo = await SignupService(session).cancel(u, event.id)
    assert not ok and err == "shifts.not_registered" and promo is None


async def test_cancel_waitlisted_decrements_waitlist(session, make_user, make_event):
    a, b = await make_user(), await make_user()
    event = await make_event(capacity=1)
    svc = SignupService(session)
    await svc.sign_up(a, event.id)  # registered
    r2, _ = await svc.sign_up(b, event.id)  # waitlisted
    assert r2.status == "waitlisted"
    await session.refresh(event)
    assert event.waitlist_count == 1

    ok, err, promo = await svc.cancel(b, event.id)  # cancel the waitlisted one
    assert ok and not err and promo is None  # no promotion for a waitlist cancel
    await session.refresh(event)
    assert event.waitlist_count == 0 and event.signup_count == 1


async def test_resignup_after_cancel_reactivates_same_row(session, make_user, make_event):
    u = await make_user()
    event = await make_event(capacity=2)
    svc = SignupService(session)
    r1, _ = await svc.sign_up(u, event.id)
    await svc.cancel(u, event.id)
    r2, err = await svc.sign_up(u, event.id)
    assert not err and r2.id == r1.id and r2.status == "registered"
    # exactly one signup row exists for this (event, user)
    rows = await SignupRepository(session).list_active_for_event(event.id, statuses=("registered",))
    assert len([r for r in rows if r.user_id == u.id]) == 1


async def test_signup_not_found(session, make_user):
    u = await make_user()
    _, err = await SignupService(session).sign_up(u, 9999)
    assert err == "shifts.not_found"


async def test_my_upcoming_lists_signups(session, make_user, make_event):
    u = await make_user()
    event = await make_event(capacity=3)
    await SignupService(session).sign_up(u, event.id)
    upcoming = await SignupService(session).list_my_upcoming(u)
    assert len(upcoming) == 1 and upcoming[0].event_id == event.id
