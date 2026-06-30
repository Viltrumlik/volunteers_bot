"""Structured logging with secret/PII redaction, plus a hardened Sentry init.

* A :class:`RedactionFilter` scrubs the bot token, Sentry DSN, and bot-token-shaped
  strings out of every emitted record so secrets never reach the log sink.
* :func:`mask_user_id` produces a stable, salted, non-reversible token so Telegram
  IDs can be correlated across logs without storing PII in plaintext.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import sys
from typing import Any

from app.config import get_settings

# Telegram bot tokens look like ``123456789:AA...`` (35+ char secret tail).
_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")


def mask_user_id(telegram_id: int | None) -> str:
    """Return a short, salted, non-reversible tag for a Telegram id (PII-safe)."""
    if telegram_id is None:
        return "anon"
    salt = get_settings().log_hash_salt.get_secret_value()
    digest = hashlib.sha256(f"{salt}:{telegram_id}".encode()).hexdigest()
    return f"u#{digest[:10]}"


class RedactionFilter(logging.Filter):
    """Strip known secrets and token-shaped substrings from formatted log output."""

    def __init__(self) -> None:
        super().__init__()
        s = get_settings()
        self._needles = [
            v
            for v in (
                s.bot_token.get_secret_value(),
                s.sentry_dsn.get_secret_value(),
                s.api_key.get_secret_value(),
            )
            if v
        ]

    def _scrub(self, text: str) -> str:
        for needle in self._needles:
            if needle and needle in text:
                text = text.replace(needle, "***")
        return _TOKEN_RE.sub("***", text)

    def filter(self, record: logging.LogRecord) -> bool:
        with contextlib.suppress(Exception):  # logging must never raise
            if isinstance(record.msg, str):
                record.msg = self._scrub(record.msg)
            if record.args:
                args = record.args if isinstance(record.args, tuple) else (record.args,)
                record.args = tuple(self._scrub(a) if isinstance(a, str) else a for a in args)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(*, json_logs: bool = False, level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactionFilter())
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s", "%H:%M:%S")
        )
    root.addHandler(handler)
    # aiogram/httpx are chatty at INFO; keep them at WARNING.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _scrub_event(event: Any, _hint: Any) -> Any:
    """Sentry before_send: drop request/user payloads that may carry PII."""
    event.pop("request", None)
    event.pop("user", None)
    return event


def init_sentry_if_configured() -> None:
    try:
        dsn = get_settings().sentry_dsn.get_secret_value()
        if not dsn:
            return
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            send_default_pii=False,
            before_send=_scrub_event,
            traces_sample_rate=0.0,
        )
        logging.getLogger(__name__).info("Sentry initialized")
    except Exception:
        logging.getLogger(__name__).exception("Sentry init failed")
