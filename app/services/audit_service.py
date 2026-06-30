"""Audit trail for privileged mutations (role changes, broadcasts, event cancels, hours adjust)."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import mask_user_id
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


async def record(
    session: AsyncSession,
    *,
    actor_telegram_id: int,
    action: str,
    target_type: str | None = None,
    target_id: str | int | None = None,
    summary: str | None = None,
) -> None:
    """Persist an audit row and emit a PII-masked log line. Never raises into the caller."""
    try:
        await AuditRepository(session).add(
            actor_telegram_id=actor_telegram_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            summary=summary,
        )
        logger.info(
            "audit action=%s actor=%s target=%s/%s",
            action,
            mask_user_id(actor_telegram_id),
            target_type,
            target_id,
        )
    except Exception:
        logger.exception("audit record failed for action=%s", action)
