"""Check-in / check-out, hours computation, admin overrides, no-show sweep, roster."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Event, EventSignup, HoursLedger, SignupStatus, User
from app.repositories.event_repository import EventRepository
from app.repositories.hours_ledger_repository import HoursLedgerRepository
from app.repositories.signup_repository import SignupRepository
from app.utils.timefmt import ensure_aware, now_utc

ROSTER_STATUSES = (
    SignupStatus.registered.value,
    SignupStatus.waitlisted.value,
    SignupStatus.checked_in.value,
    SignupStatus.checked_out.value,
    SignupStatus.no_show.value,
)
_OCCUPIES_SLOT = (
    SignupStatus.registered.value,
    SignupStatus.checked_in.value,
    SignupStatus.checked_out.value,
)


def _computed_minutes(event: Event, checked_in_at: datetime, checked_out_at: datetime) -> int:
    """Hours = clamp(out, end+grace) - clamp(in, start), capped at scheduled duration."""
    grace = timedelta(minutes=event.checkin_closes_min_after)
    starts_at, ends_at = ensure_aware(event.starts_at), ensure_aware(event.ends_at)
    start = max(ensure_aware(checked_in_at), starts_at)
    end = min(ensure_aware(checked_out_at), ends_at + grace)
    minutes = max(0, int((end - start).total_seconds() // 60))
    cap = max(0, int((ends_at - starts_at).total_seconds() // 60))
    return min(minutes, cap) if cap else minutes


class AttendanceService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._events = EventRepository(session)
        self._signups = SignupRepository(session)
        self._ledger = HoursLedgerRepository(session)

    async def check_in(self, user: User, event_id: int) -> tuple[bool, str]:
        event = await self._events.get(event_id)
        if not event:
            return False, "shifts.not_found"
        signup = await self._signups.get_for_update(event_id, user.id)
        if not signup or signup.status not in (
            SignupStatus.registered.value,
            SignupStatus.checked_in.value,
        ):
            return False, "shifts.not_registered"
        if signup.status == SignupStatus.checked_in.value:
            return False, "shifts.already_checked_in"

        now = now_utc()
        opens = ensure_aware(event.starts_at) - timedelta(minutes=event.checkin_opens_min_before)
        closes = ensure_aware(event.ends_at) + timedelta(minutes=event.checkin_closes_min_after)
        if now < opens:
            return False, "shifts.checkin_too_early"
        if now > closes:
            return False, "shifts.checkin_window_closed"

        signup.status = SignupStatus.checked_in.value
        signup.checked_in_at = now
        await self._session.flush()
        return True, ""

    async def check_out(self, user: User, event_id: int) -> tuple[bool, str, int]:
        event = await self._events.get(event_id)
        if not event:
            return False, "shifts.not_found", 0
        signup = await self._signups.get_for_update(event_id, user.id)
        if not signup or signup.status != SignupStatus.checked_in.value:
            return False, "shifts.not_checked_in", 0

        checked_in_at = signup.checked_in_at or event.starts_at
        checked_out_at = now_utc()
        signup.status = SignupStatus.checked_out.value
        signup.checked_out_at = checked_out_at
        minutes = _computed_minutes(event, checked_in_at, checked_out_at)
        await self._session.flush()
        # Idempotent: the partial-unique (signup_id) WHERE source='auto' blocks double credit.
        await self._ledger.upsert_auto_entry(signup.id, user.id, event.id, minutes)
        return True, "", minutes

    async def admin_mark(self, signup_id: int, state: str) -> tuple[EventSignup | None, str]:
        if state not in (
            SignupStatus.checked_in.value,
            SignupStatus.checked_out.value,
            SignupStatus.no_show.value,
        ):
            return None, "errors.generic"
        signup = await self._signups.get_by_id_for_update(signup_id)
        if not signup:
            return None, "shifts.not_found"
        event = await self._events.get_for_update(signup.event_id)
        was = signup.status
        if state == SignupStatus.no_show.value and was in _OCCUPIES_SLOT and event:
            event.signup_count = max(0, event.signup_count - 1)
        signup.status = state
        if state == SignupStatus.checked_in.value and signup.checked_in_at is None:
            signup.checked_in_at = now_utc()
        await self._session.flush()
        return signup, ""

    async def admin_adjust_hours(
        self, *, admin: User, signup_id: int, minutes: int, note: str
    ) -> tuple[HoursLedger | None, str]:
        if not note.strip():
            return None, "admin_attendance.note_required"
        signup = await self._signups.get_by_id_for_update(signup_id)
        if not signup:
            return None, "shifts.not_found"
        entry = await self._ledger.add_admin_adjust(
            user_id=signup.user_id,
            event_id=signup.event_id,
            signup_id=signup.id,
            minutes=minutes,
            note=note.strip()[:2000],
            created_by=admin.id,
        )
        return entry, ""

    async def sweep_no_shows(self, event_id: int) -> int:
        """Flip 'registered' (never checked in) past the grace window to 'no_show'."""
        event = await self._events.get_for_update(event_id)
        if not event:
            return 0
        threshold = ensure_aware(event.starts_at) + timedelta(minutes=event.no_show_grace_min)
        if now_utc() <= threshold:
            return 0
        candidates = await self._signups.list_registered_not_checked_in(event_id)
        count = 0
        for s in candidates:
            s.status = SignupStatus.no_show.value
            event.signup_count = max(0, event.signup_count - 1)
            count += 1
        if count:
            await self._session.flush()
        return count

    async def roster(
        self, event_id: int, *, page: int = 1, per_page: int = 8
    ) -> tuple[list[EventSignup], int]:
        total = await self._signups.count_active_for_event(event_id, statuses=ROSTER_STATUSES)
        pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, pages))
        rows = await self._signups.list_active_for_event(
            event_id, statuses=ROSTER_STATUSES, limit=per_page, offset=(page - 1) * per_page
        )
        return rows, pages
