from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import News, NewsStatus


class NewsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_pending(
        self,
        *,
        created_by_telegram_id: int,
        text: str | None,
        photo_file_id: str | None,
        buttons_raw: str | None,
    ) -> News:
        n = News(
            created_by_telegram_id=created_by_telegram_id,
            text=text,
            photo_file_id=photo_file_id,
            buttons_raw=buttons_raw,
            status=NewsStatus.pending.value,
        )
        self.session.add(n)
        await self.session.flush()
        return n

    async def get(self, news_id: int) -> News | None:
        r = await self.session.execute(select(News).where(News.id == news_id))
        return r.scalar_one_or_none()

    async def mark_sending(self, news_id: int) -> None:
        await self.session.execute(
            update(News).where(News.id == news_id).values(status=NewsStatus.sending.value)
        )

    async def mark_completed(self, news_id: int, sent_ok: int, sent_fail: int) -> None:
        await self.session.execute(
            update(News)
            .where(News.id == news_id)
            .values(
                status=NewsStatus.completed.value,
                sent_ok=sent_ok,
                sent_fail=sent_fail,
                finished_at=datetime.now(UTC),
            )
        )

    async def mark_failed(self, news_id: int, err: str) -> None:
        await self.session.execute(
            update(News)
            .where(News.id == news_id)
            .values(
                status=NewsStatus.failed.value,
                error_message=err[:4000],
                finished_at=datetime.now(UTC),
            )
        )
