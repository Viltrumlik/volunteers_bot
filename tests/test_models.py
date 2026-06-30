from datetime import timedelta

import pytest
from app.database.models import Event
from app.utils.timefmt import now_utc
from sqlalchemy.exc import IntegrityError


async def test_capacity_check_constraint(session):
    starts = now_utc() + timedelta(hours=1)
    session.add(
        Event(
            title="x", tz="UTC", starts_at=starts, ends_at=starts + timedelta(hours=1), capacity=0
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_time_order_check_constraint(session):
    starts = now_utc() + timedelta(hours=2)
    session.add(
        Event(
            title="x", tz="UTC", starts_at=starts, ends_at=starts - timedelta(hours=1), capacity=1
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_signup_unique(session, make_user, make_event):
    from app.database.models import EventSignup

    user = await make_user()
    event = await make_event(capacity=5)
    session.add(EventSignup(event_id=event.id, user_id=user.id, status="registered"))
    await session.flush()
    session.add(EventSignup(event_id=event.id, user_id=user.id, status="waitlisted"))
    with pytest.raises(IntegrityError):
        await session.flush()
