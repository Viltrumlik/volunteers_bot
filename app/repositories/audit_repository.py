from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        *,
        actor_telegram_id: int,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        summary: str | None = None,
    ) -> AuditLog:
        row = AuditLog(
            actor_telegram_id=actor_telegram_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            summary=(summary or None) and summary[:4000],
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_recent(self, *, limit: int = 50) -> list[AuditLog]:
        r = await self.session.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        )
        return list(r.scalars().all())
