from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Ticket, TicketStatus, User
from app.repositories.ticket_repository import TicketRepository


class TicketService:
    def __init__(self, session: AsyncSession):
        self._repo = TicketRepository(session)

    async def create(
        self,
        user: User,
        body_text: str,
        *,
        ticket_type: str = "help",
        priority: str | None = None,
    ) -> Ticket:
        return await self._repo.create(
            user.id, body_text, ticket_type=ticket_type, priority=priority
        )

    async def add_admin_message(
        self,
        ticket_id: int,
        body_text: str,
        *,
        telegram_message_id: int | None = None,
    ) -> None:
        await self._repo.add_message(
            ticket_id,
            direction="admin",
            body_text=body_text,
            telegram_message_id=telegram_message_id,
        )
        await self._repo.mark_first_response_if_needed(ticket_id)

    async def set_admin_delivery(
        self,
        ticket_id: int,
        *,
        message_id: int,
        thread_id: int | None = None,
    ) -> None:
        await self._repo.set_admin_delivery(ticket_id, message_id=message_id, thread_id=thread_id)

    async def get_by_admin_root_message(self, message_id: int) -> Ticket | None:
        return await self._repo.get_by_admin_root_message(message_id)

    async def get_by_admin_message_chain(self, message_ids: list[int]) -> Ticket | None:
        return await self._repo.get_by_admin_message_chain(message_ids)

    async def close(self, ticket_id: int) -> bool:
        return await self._repo.set_status(ticket_id, TicketStatus.closed.value)

    async def mark_in_progress(self, ticket_id: int) -> bool:
        return await self._repo.set_status(ticket_id, TicketStatus.in_progress.value)

    async def get(self, ticket_id: int) -> Ticket | None:
        return await self._repo.get(ticket_id)

    async def load_user(self, ticket: Ticket) -> User | None:
        return await self._repo.load_user(ticket)

    async def assign(self, ticket_id: int, admin_telegram_id: int) -> None:
        await self._repo.assign(ticket_id, admin_telegram_id)
