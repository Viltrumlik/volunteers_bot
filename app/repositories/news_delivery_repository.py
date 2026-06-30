from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import NewsDelivery, NewsDeliveryStatus


class NewsDeliveryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_row(self, news_id: int, user_telegram_id: int) -> NewsDelivery:
        """Idempotent get-or-create for (news_id, user_telegram_id)."""
        row = await self._get_pair(news_id, user_telegram_id)
        if row:
            return row
        d = NewsDelivery(
            news_id=news_id,
            user_telegram_id=user_telegram_id,
            status=NewsDeliveryStatus.pending.value,
        )
        self.session.add(d)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            row = await self._get_pair(news_id, user_telegram_id)
            if row:
                return row
            raise
        return d

    async def _get_pair(self, news_id: int, user_telegram_id: int) -> NewsDelivery | None:
        r = await self.session.execute(
            select(NewsDelivery).where(
                NewsDelivery.news_id == news_id,
                NewsDelivery.user_telegram_id == user_telegram_id,
            )
        )
        return r.scalar_one_or_none()

    async def mark_sent(self, delivery_id: int) -> None:
        now = datetime.now(UTC)
        await self.session.execute(
            update(NewsDelivery)
            .where(NewsDelivery.id == delivery_id)
            .values(
                status=NewsDeliveryStatus.sent.value,
                sent_at=now,
                updated_at=now,
            )
        )

    async def record_failure(self, delivery_id: int, error: str, *, attempts: int) -> None:
        await self.session.execute(
            update(NewsDelivery)
            .where(NewsDelivery.id == delivery_id)
            .values(
                status=NewsDeliveryStatus.failed.value,
                last_error=error[:4000],
                attempts=attempts,
                updated_at=datetime.now(UTC),
            )
        )

    async def mark_dead_letter(self, delivery_id: int, error: str, *, attempts: int = 0) -> None:
        await self.session.execute(
            update(NewsDelivery)
            .where(NewsDelivery.id == delivery_id)
            .values(
                status=NewsDeliveryStatus.dead_letter.value,
                last_error=error[:4000],
                attempts=attempts,
                updated_at=datetime.now(UTC),
            )
        )
