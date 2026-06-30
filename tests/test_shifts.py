from datetime import timedelta

from app.services.attendance_service import AttendanceService, _computed_minutes
from app.services.event_service import EventService
from app.services.hours_service import HoursService
from app.services.signup_service import SignupService
from app.utils.timefmt import now_utc


async def test_signup_waitlist_and_promotion(session, make_user, make_event):
    a, b = await make_user(), await make_user()
    event = await make_event(capacity=1)
    svc = SignupService(session)

    r1, e1 = await svc.sign_up(a, event.id)
    assert r1 and r1.status == "registered" and not e1
    r2, e2 = await svc.sign_up(b, event.id)
    assert r2 and r2.status == "waitlisted" and not e2

    await session.refresh(event)
    assert (event.signup_count, event.waitlist_count) == (1, 1)

    # duplicate
    _, err = await svc.sign_up(a, event.id)
    assert err == "shifts.already_registered"

    # cancel A -> B promoted
    ok, err, promo = await svc.cancel(a, event.id)
    assert ok and promo and promo.telegram_id == b.telegram_id
    await session.refresh(event)
    assert (event.signup_count, event.waitlist_count) == (1, 0)


async def test_signup_closed_event(session, make_user, make_event):
    u = await make_user()
    event = await make_event(capacity=3, status="closed")
    _, err = await SignupService(session).sign_up(u, event.id)
    assert err == "shifts.closed"


async def test_cannot_sign_up_after_start(session, make_user, make_event):
    u = await make_user()
    event = await make_event(capacity=3)
    event.starts_at = now_utc() - timedelta(minutes=5)
    await session.flush()
    _, err = await SignupService(session).sign_up(u, event.id)
    assert err == "shifts.already_started"


def test_hours_clamp_and_cap():
    class E:
        starts_at = now_utc()
        ends_at = now_utc() + timedelta(hours=3)
        checkin_closes_min_after = 120

    assert _computed_minutes(E, E.starts_at, E.starts_at + timedelta(hours=2)) == 120
    # forgot to check out -> capped at scheduled duration (3h)
    assert _computed_minutes(E, E.starts_at, E.starts_at + timedelta(hours=10)) == 180
    # checked in early -> clamped to start
    assert (
        _computed_minutes(E, E.starts_at - timedelta(hours=1), E.starts_at + timedelta(hours=1))
        == 60
    )


async def test_checkin_checkout_and_double_checkout(session, make_user, make_event):
    u = await make_user()
    event = await make_event(capacity=3)
    await SignupService(session).sign_up(u, event.id)
    await session.flush()
    event.starts_at = now_utc() - timedelta(minutes=10)  # window open
    await session.flush()

    att = AttendanceService(session)
    ok, err = await att.check_in(u, event.id)
    assert ok, err
    ok, err, _ = await att.check_out(u, event.id)
    assert ok, err
    # double check-out blocked
    ok2, err2, _ = await att.check_out(u, event.id)
    assert not ok2 and err2 == "shifts.not_checked_in"

    summary = await HoursService(session).my_summary(u)
    assert summary.attended_count == 1


async def test_checkin_too_early(session, make_user, make_event):
    u = await make_user()
    event = await make_event(capacity=3, hours_from_now=48)  # far future
    await SignupService(session).sign_up(u, event.id)
    await session.flush()
    ok, err = await AttendanceService(session).check_in(u, event.id)
    assert not ok and err == "shifts.checkin_too_early"


async def test_no_show_sweep(session, make_user, make_event):
    u = await make_user()
    event = await make_event(capacity=3)
    await SignupService(session).sign_up(u, event.id)
    await session.flush()
    event.starts_at = now_utc() - timedelta(hours=2)  # well past grace
    await session.flush()
    flipped = await AttendanceService(session).sweep_no_shows(event.id)
    assert flipped == 1
    await session.refresh(event)
    assert event.signup_count == 0


async def test_admin_adjust_requires_note(session, make_user, make_event):
    admin = await make_user(role="admin")
    u = await make_user()
    event = await make_event(capacity=3)
    signup, _ = await SignupService(session).sign_up(u, event.id)
    att = AttendanceService(session)
    _, err = await att.admin_adjust_hours(admin=admin, signup_id=signup.id, minutes=30, note="  ")
    assert err == "admin_attendance.note_required"
    entry, err = await att.admin_adjust_hours(
        admin=admin, signup_id=signup.id, minutes=-15, note="correction"
    )
    assert entry and not err
    total = await HoursService(session)._ledger.total_minutes_for_user(u.id)
    assert total == -15


async def test_cancel_event_lists_recipients(session, make_user, make_event):
    a, b = await make_user(), await make_user()
    event = await make_event(capacity=5)
    await SignupService(session).sign_up(a, event.id)
    await SignupService(session).sign_up(b, event.id)
    recipients, err = await EventService(session).cancel(event.id)
    assert not err and {r[0] for r in recipients} == {a.telegram_id, b.telegram_id}
    await session.refresh(event)
    assert event.status == "cancelled"
