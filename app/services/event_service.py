"""Admin-side shift (event) lifecycle: create, edit, close, cancel."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import Event, EventStatus, SignupStatus
from app.repositories.event_repository import EventRepository
from app.repositories.signup_repository import SignupRepository
from app.utils.timefmt import now_utc, valid_tz

# Statuses whose holders should be notified when an event is cancelled.
_NOTIFY_ON_CANCEL = (
    SignupStatus.registered.value,
    SignupStatus.waitlisted.value,
    SignupStatus.checked_in.value,
    SignupStatus.checked_out.value,
)


class EventService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._events = EventRepository(session)
        self._signups = SignupRepository(session)

    async def get(self, event_id: int) -> Event | None:
        return await self._events.get(event_id)

    async def list_upcoming(
        self, *, page: int = 1, region_id: int | None = None
    ) -> tuple[list[Event], int]:
        return await self._events.list_upcoming(now_utc(), page=page, region_id=region_id)

    async def list_for_admin(self, *, page: int = 1) -> tuple[list[Event], int]:
        return await self._events.list_for_admin(page=page)

    async def create(
        self,
        *,
        admin_user_id: int | None,
        title: str,
        description: str,
        location: str,
        region_id: int | None,
        tz: str,
        starts_at: datetime,
        ends_at: datetime,
        capacity: int,
    ) -> tuple[Event | None, str]:
        if not valid_tz(tz):
            return None, "shifts.bad_tz"
        if ends_at <= starts_at:
            return None, "admin_events.bad_time_order"
        if starts_at <= now_utc():
            return None, "admin_events.start_in_past"
        if capacity <= 0:
            return None, "admin_events.bad_capacity"
        event = await self._events.create(
            title=title.strip()[:255],
            description=description.strip(),
            location=location.strip()[:512],
            region_id=region_id,
            tz=tz or get_settings().default_event_tz,
            starts_at=starts_at,
            ends_at=ends_at,
            capacity=capacity,
            status=EventStatus.open.value,
            created_by=admin_user_id,
        )
        return event, ""

    async def set_text_field(
        self, event_id: int, field: str, value: str
    ) -> tuple[Event | None, str]:
        if field not in ("title", "description", "location"):
            return None, "errors.generic"
        event = await self._events.get_for_update(event_id)
        if not event:
            return None, "shifts.not_found"
        setattr(event, field, value.strip()[:512])
        await self._session.flush()
        return event, ""

    async def set_capacity(self, event_id: int, capacity: int) -> tuple[Event | None, str]:
        if capacity <= 0:
            return None, "admin_events.bad_capacity"
        event = await self._events.get_for_update(event_id)
        if not event:
            return None, "shifts.not_found"
        if capacity < event.signup_count:
            return None, "admin_events.capacity_below_signups"
        event.capacity = capacity
        await self._session.flush()
        return event, ""

    async def set_times(
        self, event_id: int, starts_at: datetime, ends_at: datetime
    ) -> tuple[Event | None, str]:
        if ends_at <= starts_at:
            return None, "admin_events.bad_time_order"
        if starts_at <= now_utc():
            return None, "admin_events.start_in_past"
        event = await self._events.get_for_update(event_id)
        if not event:
            return None, "shifts.not_found"
        event.starts_at = starts_at
        event.ends_at = ends_at
        await self._session.flush()
        return event, ""

    async def close(self, event_id: int) -> tuple[Event | None, str]:
        event = await self._events.get_for_update(event_id)
        if not event:
            return None, "shifts.not_found"
        if event.status == EventStatus.cancelled.value:
            return None, "admin_events.already_cancelled"
        event.status = EventStatus.closed.value
        await self._session.flush()
        return event, ""

    async def cancel(self, event_id: int) -> tuple[list[tuple[int, str, str]] | None, str]:
        """Cancel the event. Returns the list of (telegram_id, language, title) to notify."""
        event = await self._events.get_for_update(event_id)
        if not event:
            return None, "shifts.not_found"
        if event.status == EventStatus.cancelled.value:
            return None, "admin_events.already_cancelled"
        event.status = EventStatus.cancelled.value
        signups = await self._signups.list_active_for_event(event_id, statuses=_NOTIFY_ON_CANCEL)
        await self._session.flush()
        return [(s.user.telegram_id, s.user.language, event.title) for s in signups], ""
