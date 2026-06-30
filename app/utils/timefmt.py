"""Timezone helpers for shifts.

Instants are stored UTC and tz-aware. Events carry an IANA tz name used only for
*display* and for *parsing admin input*. Reminder offsets are applied to the UTC
instant elsewhere, so this module never does wall-clock arithmetic (DST-safe).
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_INPUT_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d.%m.%Y %H:%M")


def valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_aware(dt: datetime) -> datetime:
    """Treat a naive datetime as UTC.

    SQLite returns naive datetimes for ``DateTime(timezone=True)`` columns (Postgres
    returns aware ones), so DB-sourced timestamps must be normalized before they are
    compared to :func:`now_utc` or formatted.
    """
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def parse_local_to_utc(text: str, tz_name: str) -> datetime | None:
    """Parse ``YYYY-MM-DD HH:MM`` (etc.) entered in ``tz_name`` into a UTC instant."""
    raw = (text or "").strip()
    if not valid_tz(tz_name):
        return None
    tz = ZoneInfo(tz_name)
    for fmt in _INPUT_FORMATS:
        try:
            naive = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=tz).astimezone(UTC)
    return None


def format_local(dt: datetime, tz_name: str) -> str:
    """Render a UTC instant in the event's local tz with an explicit tz suffix."""
    tz = ZoneInfo(tz_name) if valid_tz(tz_name) else UTC
    local = ensure_aware(dt).astimezone(tz)
    return f"{local:%Y-%m-%d %H:%M} ({tz_name})"


def format_short(dt: datetime, tz_name: str) -> str:
    """Compact local time for inline buttons (no tz suffix)."""
    tz = ZoneInfo(tz_name) if valid_tz(tz_name) else UTC
    return f"{ensure_aware(dt).astimezone(tz):%m-%d %H:%M}"


def format_range(starts_at: datetime, ends_at: datetime, tz_name: str) -> str:
    tz = ZoneInfo(tz_name) if valid_tz(tz_name) else UTC
    s, e = ensure_aware(starts_at).astimezone(tz), ensure_aware(ends_at).astimezone(tz)
    if s.date() == e.date():
        return f"{s:%Y-%m-%d %H:%M}–{e:%H:%M} ({tz_name})"
    return f"{s:%Y-%m-%d %H:%M} → {e:%Y-%m-%d %H:%M} ({tz_name})"
