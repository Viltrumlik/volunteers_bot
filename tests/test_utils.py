from datetime import UTC, datetime

from app.utils.formatting import format_suggestion_header, format_ticket_header
from app.utils.phone import is_valid_phone, normalize_phone_digits, store_phone
from app.utils.timefmt import (
    ensure_aware,
    format_local,
    format_range,
    format_short,
    parse_local_to_utc,
    valid_tz,
)
from app.utils.validation import validate_age_text, validate_bio


def test_validate_age():
    assert validate_age_text("25") == 25
    assert validate_age_text("4") is None  # too young
    assert validate_age_text("200") is None  # too old
    assert validate_age_text("abc") is None


def test_validate_bio():
    assert validate_bio("  hello ") == "hello"
    assert validate_bio("   ") is None
    assert validate_bio("x" * 5000) is None


def test_phone_helpers():
    assert normalize_phone_digits("+998 (90) 123-45-67") == "998901234567"
    assert is_valid_phone("998901234567")
    assert not is_valid_phone("123")
    assert store_phone("  +99890  ") == "+99890"
    assert len(store_phone("9" * 200)) == 64


def test_timefmt_parse_and_format():
    assert valid_tz("Asia/Tashkent")
    assert not valid_tz("Not/AZone")
    dt = parse_local_to_utc("2026-07-01 09:00", "UTC")
    assert dt is not None and dt.tzinfo is not None and dt.hour == 9
    assert parse_local_to_utc("nonsense", "UTC") is None
    assert parse_local_to_utc("2026-07-01 09:00", "Bad/Zone") is None
    naive = datetime(2026, 7, 1, 9, 0)
    assert ensure_aware(naive).tzinfo is UTC
    aware = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    assert "Asia/Tashkent" in format_local(aware, "Asia/Tashkent")
    assert "→" in format_range(aware, datetime(2026, 7, 3, 9, 0, tzinfo=UTC), "UTC")
    assert format_short(aware, "UTC") == "07-01 09:00"


def test_formatting_escapes(make_user):
    class U:
        telegram_id = 5
        full_name = "<b>x</b>"

    h = format_ticket_header(1, U, "user<>")
    assert "&lt;b&gt;" in h and "<b>x</b>" not in h
    s = format_suggestion_header(2, U, None)
    assert "Suggestion" in s
