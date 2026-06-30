"""
Google Sheets reporting via service account (gspread).

Setup:
1. Google Cloud console: enable Sheets API, create service account, download JSON key.
2. Create spreadsheet; share with service account email (Editor).
3. GOOGLE_CREDENTIALS_PATH, GOOGLE_SHEET_ID in .env.

Tabs: Users, Applications, Tickets (headers created automatically).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

USERS_HEADERS = [
    "Telegram ID",
    "Full Name",
    "Age",
    "Region",
    "Gender",
    "Role",
    "Phone",
    "Bio",
    "Registration Date",
]
APPS_HEADERS = ["User Name", "Project Name", "Status", "Applied At"]
TICKETS_HEADERS = ["User", "Type", "Status", "Created At"]


@lru_cache
def _spreadsheet():
    settings = get_settings()
    sid = (settings.google_sheet_id or "").strip()
    inline = settings.google_credentials_json.get_secret_value().strip()
    path = (settings.google_credentials_path or "").strip()
    if not sid or not (inline or path):
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        # Prefer inline JSON (secret manager / env) over an on-disk path.
        if inline:
            creds = Credentials.from_service_account_info(json.loads(inline), scopes=scopes)
        else:
            creds = Credentials.from_service_account_file(path, scopes=scopes)
        gc = gspread.authorize(creds)
        return gc.open_by_key(sid)
    except Exception:
        # Do not log the exception detail — it can contain the key path / SA email.
        logger.warning("Google Sheets client init failed (check credentials/sheet id)")
        return None


def _retry(fn: Callable[[], Any], max_attempts: int = 4) -> Any:
    last = None
    for i in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(0.5 * (2**i) + random.uniform(0, 0.2))  # noqa: S311 (retry jitter, not crypto)
    if last:
        raise last


class GoogleSheetsService:
    def _users_ws(self):
        sh = _spreadsheet()
        if sh is None:
            return None
        try:
            return _retry(lambda: sh.worksheet("Users"))
        except Exception:
            return _retry(lambda: sh.add_worksheet(title="Users", rows=2000, cols=12))

    def _ensure_headers(self, ws, headers: list[str]) -> None:
        rows = _retry(lambda: ws.get_all_values())
        if not rows or rows[0] != headers:
            _retry(lambda: ws.update("A1", [headers]))

    def _upsert_user_sync(self, user, region_label: str) -> None:
        ws = self._users_ws()
        if ws is None:
            return
        self._ensure_headers(ws, USERS_HEADERS)
        tid = str(user.telegram_id)
        rows = _retry(lambda: ws.get_all_values())
        reg = user.created_at
        reg_s = reg.isoformat() if hasattr(reg, "isoformat") else str(reg)
        row = [
            tid,
            user.full_name or "",
            str(user.age) if user.age is not None else "",
            region_label,
            user.gender or "",
            user.role or "",
            user.phone or "",
            (user.bio or "")[:5000],
            reg_s,
        ]
        for i, r in enumerate(rows[1:], start=2):
            if r and r[0] == tid:
                _retry(lambda i=i, row=row: ws.update(f"A{i}:I{i}", [row]))
                return
        _retry(lambda: ws.append_row(row, value_input_option="USER_ENTERED"))

    async def add_user(self, user, region_label: str = "") -> None:
        await asyncio.to_thread(self._upsert_user_sync, user, region_label)

    async def update_user(self, user, region_label: str = "") -> None:
        await self.add_user(user, region_label=region_label)

    def _log_application_sync(self, application, user_name: str, project_name: str) -> None:
        sh = _spreadsheet()
        if sh is None:
            return
        try:
            ws = _retry(lambda: sh.worksheet("Applications"))
        except Exception:
            ws = _retry(lambda: sh.add_worksheet(title="Applications", rows=3000, cols=10))
        self._ensure_headers(ws, APPS_HEADERS)
        ts = application.created_at
        ts_s = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        _retry(
            lambda: ws.append_row(
                [user_name, project_name, application.status, ts_s],
                value_input_option="USER_ENTERED",
            )
        )

    async def log_application(self, application, user_name: str, project_name: str) -> None:
        await asyncio.to_thread(self._log_application_sync, application, user_name, project_name)

    def _log_ticket_sync(self, ticket, user_label: str) -> None:
        sh = _spreadsheet()
        if sh is None:
            return
        try:
            ws = _retry(lambda: sh.worksheet("Tickets"))
        except Exception:
            ws = _retry(lambda: sh.add_worksheet(title="Tickets", rows=3000, cols=10))
        self._ensure_headers(ws, TICKETS_HEADERS)
        ts = ticket.created_at
        ts_s = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        _retry(
            lambda: ws.append_row(
                [user_label, ticket.ticket_type, ticket.status, ts_s],
                value_input_option="USER_ENTERED",
            )
        )

    async def log_ticket(self, ticket, user_label: str) -> None:
        await asyncio.to_thread(self._log_ticket_sync, ticket, user_label)


async def safe_add_user(user, region_label: str = "") -> None:
    try:
        await GoogleSheetsService().add_user(user, region_label=region_label)
    except Exception:
        logger.exception("Google Sheets add_user failed")


async def safe_log_application(application, user_name: str, project_name: str) -> None:
    try:
        await GoogleSheetsService().log_application(application, user_name, project_name)
    except Exception:
        logger.exception("Google Sheets log_application failed")


async def safe_log_ticket(ticket, user_label: str) -> None:
    try:
        await GoogleSheetsService().log_ticket(ticket, user_label)
    except Exception:
        logger.exception("Google Sheets log_ticket failed")


async def enqueue_add_user(user, region_label: str = "") -> None:
    from app.integrations.sheets_outbox import enqueue

    async def job() -> None:
        await safe_add_user(user, region_label=region_label)

    await enqueue(job)


async def enqueue_log_application(application, user_name: str, project_name: str) -> None:
    from app.integrations.sheets_outbox import enqueue

    async def job() -> None:
        await safe_log_application(application, user_name, project_name)

    await enqueue(job)


async def enqueue_log_ticket(ticket, user_label: str) -> None:
    from app.integrations.sheets_outbox import enqueue

    async def job() -> None:
        await safe_log_ticket(ticket, user_label)

    await enqueue(job)
