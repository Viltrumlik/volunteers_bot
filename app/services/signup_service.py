"""Volunteer signup / waitlist / cancel with race-free capacity.

Capacity is serialized by a row lock on the ``events`` row (the project's own idiom);
the ``event_signups`` UNIQUE(event_id, user_id) is the independent backstop. Lock order
is always event → signup → waitlist-head to avoid deadlock.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Event, EventSignup, EventStatus, SignupStatus, User
from app.repositories.event_repository import EventRepository
from app.repositories.signup_repository import SignupRepository
from app.utils.timefmt import ensure_aware, now_utc

_OCCUPIES_SLOT = (
    SignupStatus.registered.value,
    SignupStatus.checked_in.value,
    SignupStatus.checked_out.value,
)


@dataclass(slots=True)
class Promotion:
    telegram_id: int
    language: str
    event_title: str


class SignupService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._events = EventRepository(session)
        self._signups = SignupRepository(session)

    async def sign_up(self, user: User, event_id: int) -> tuple[EventSignup | None, str]:
        event = await self._events.get_for_update(event_id)
        if not event:
            return None, "shifts.not_found"
        if event.status != EventStatus.open.value:
            return None, "shifts.closed"
        if ensure_aware(event.starts_at) <= now_utc():
            return None, "shifts.already_started"

        existing = await self._signups.get_for_update(event_id, user.id)
        if existing and existing.status in _OCCUPIES_SLOT:
            return None, "shifts.already_registered"
        if existing and existing.status == SignupStatus.waitlisted.value:
            return None, "shifts.already_waitlisted"

        if event.signup_count < event.capacity:
            status = SignupStatus.registered.value
            event.signup_count += 1
            waitlist_pos = None
        else:
            status = SignupStatus.waitlisted.value
            event.waitlist_count += 1
            waitlist_pos = await self._signups.next_waitlist_pos(event_id)

        if existing:  # reactivate a cancelled / no_show row (keeps the UNIQUE intact)
            existing.status = status
            existing.waitlist_pos = waitlist_pos
            existing.cancelled_at = None
            existing.checked_in_at = None
            existing.checked_out_at = None
            row = existing
        else:
            row = await self._signups.create(event_id, user.id, status, waitlist_pos)
        await self._session.flush()
        return row, ""

    async def cancel(self, user: User, event_id: int) -> tuple[bool, str, Promotion | None]:
        event = await self._events.get_for_update(event_id)
        if not event:
            return False, "shifts.not_found", None
        signup = await self._signups.get_for_update(event_id, user.id)
        if not signup or signup.status in (
            SignupStatus.cancelled.value,
            SignupStatus.no_show.value,
        ):
            return False, "shifts.not_registered", None

        was = signup.status
        signup.status = SignupStatus.cancelled.value
        signup.cancelled_at = now_utc()
        signup.waitlist_pos = None

        promotion: Promotion | None = None
        if was == SignupStatus.waitlisted.value:
            event.waitlist_count = max(0, event.waitlist_count - 1)
        elif was in _OCCUPIES_SLOT:
            event.signup_count = max(0, event.signup_count - 1)
            promotion = await self._promote_waitlist_head(event)
        await self._session.flush()
        return True, "", promotion

    async def _promote_waitlist_head(self, event: Event) -> Promotion | None:
        head = await self._signups.pop_first_waitlisted_for_update(event.id)
        if not head:
            return None
        head.status = SignupStatus.registered.value
        head.waitlist_pos = None
        event.signup_count += 1
        event.waitlist_count = max(0, event.waitlist_count - 1)
        return Promotion(head.user.telegram_id, head.user.language, event.title)

    async def list_my_upcoming(self, user: User) -> list[EventSignup]:
        return await self._signups.list_upcoming_for_user(user.id, now_utc())
