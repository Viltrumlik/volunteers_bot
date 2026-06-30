from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Suggestion, User


class SuggestionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user: User, text: str) -> Suggestion:
        s = Suggestion(user_id=user.id, text=text)
        self.session.add(s)
        await self.session.flush()
        return s

    async def set_admin_message_id(self, suggestion_id: int, message_id: int) -> None:
        await self.session.execute(
            update(Suggestion)
            .where(Suggestion.id == suggestion_id)
            .values(admin_message_id=message_id)
        )
