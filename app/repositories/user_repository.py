from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Region, User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        r = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return r.scalar_one_or_none()

    async def touch_activity(self, telegram_id: int, username: str | None = None) -> None:
        vals: dict[str, object] = {"last_active_at": datetime.now(UTC)}
        if username is not None:
            vals["username"] = username
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(**vals)
        )

    async def count_users(self) -> int:
        r = await self.session.execute(select(func.count()).select_from(User))
        return int(r.scalar_one())

    async def count_active_users(self, days: int = 7) -> int:
        since = datetime.now(UTC) - timedelta(days=days)
        r = await self.session.execute(
            select(func.count()).select_from(User).where(User.last_active_at >= since)
        )
        return int(r.scalar_one())

    async def list_users_page(
        self,
        page: int = 1,
        per_page: int = 8,
        query: str | None = None,
    ) -> tuple[list[User], int]:
        base = select(User).outerjoin(Region, User.region_id == Region.id)
        filters = []
        if query and query.strip():
            term = f"%{query.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(User.full_name).like(term),
                    func.lower(func.coalesce(User.phone, "")).like(term),
                    func.lower(func.coalesce(Region.name_uz, "")).like(term),
                    func.lower(func.coalesce(Region.name_ru, "")).like(term),
                    func.lower(func.coalesce(User.username, "")).like(term),
                )
            )
        count_stmt = (
            select(func.count()).select_from(User).outerjoin(Region, User.region_id == Region.id)
        )
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = int((await self.session.execute(count_stmt)).scalar_one())
        pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, pages))
        offset = (page - 1) * per_page
        stmt = base.order_by(User.created_at.desc())
        if filters:
            stmt = stmt.where(*filters)
        r = await self.session.execute(stmt.offset(offset).limit(per_page))
        return list(r.scalars().all()), pages

    async def all_telegram_ids(self) -> list[int]:
        r = await self.session.execute(select(User.telegram_id))
        return [row[0] for row in r.all()]
