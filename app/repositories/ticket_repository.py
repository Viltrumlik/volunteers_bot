from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Ticket, TicketMessage, TicketPriority, TicketStatus, User


class TicketRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: int,
        body_text: str,
        *,
        ticket_type: str = "help",
        priority: str | None = None,
    ) -> Ticket:
        pr = priority or TicketPriority.medium.value
        t = Ticket(
            user_id=user_id,
            body_text=body_text,
            status=TicketStatus.open.value,
            priority=pr,
            ticket_type=ticket_type,
        )
        self.session.add(t)
        await self.session.flush()
        m = TicketMessage(ticket_id=t.id, direction="user", body_text=body_text)
        self.session.add(m)
        await self.session.flush()
        return t

    async def add_message(
        self,
        ticket_id: int,
        *,
        direction: str,
        body_text: str,
        telegram_message_id: int | None = None,
    ) -> TicketMessage:
        m = TicketMessage(
            ticket_id=ticket_id,
            direction=direction,
            body_text=body_text,
            telegram_message_id=telegram_message_id,
        )
        self.session.add(m)
        await self.session.flush()
        return m

    async def get_for_update(self, ticket_id: int) -> Ticket | None:
        stmt = select(Ticket).where(Ticket.id == ticket_id).with_for_update(of=Ticket)
        r = await self.session.execute(stmt)
        return r.scalar_one_or_none()

    async def set_admin_delivery(
        self,
        ticket_id: int,
        *,
        message_id: int,
        thread_id: int | None = None,
    ) -> None:
        vals: dict[str, object] = {"admin_message_id": message_id}
        if thread_id is not None:
            vals["admin_thread_id"] = thread_id
        await self.session.execute(update(Ticket).where(Ticket.id == ticket_id).values(**vals))

    async def mark_first_response_if_needed(self, ticket_id: int) -> None:
        now = datetime.now(UTC)
        await self.session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id, Ticket.first_response_at.is_(None))
            .values(first_response_at=now, updated_at=now)
        )

    async def assign(self, ticket_id: int, admin_telegram_id: int) -> None:
        await self.session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(assigned_telegram_id=admin_telegram_id, updated_at=datetime.now(UTC))
        )

    async def get_by_admin_root_message(self, message_id: int) -> Ticket | None:
        r = await self.session.execute(select(Ticket).where(Ticket.admin_message_id == message_id))
        return r.scalar_one_or_none()

    async def get_by_admin_message_chain(self, message_ids: list[int]) -> Ticket | None:
        if not message_ids:
            return None
        r = await self.session.execute(
            select(Ticket).where(Ticket.admin_message_id.in_(message_ids))
        )
        tickets = list(r.scalars().all())
        if not tickets:
            return None
        pos = {mid: i for i, mid in enumerate(message_ids)}
        tickets.sort(key=lambda t: pos.get(t.admin_message_id or 0, 9999))
        return tickets[0]

    async def set_status(self, ticket_id: int, status: str) -> bool:
        vals: dict[str, object] = {"status": status, "updated_at": datetime.now(UTC)}
        if status == TicketStatus.closed.value:
            vals["closed_at"] = datetime.now(UTC)
        r = await self.session.execute(update(Ticket).where(Ticket.id == ticket_id).values(**vals))
        return r.rowcount > 0

    async def get(self, ticket_id: int) -> Ticket | None:
        r = await self.session.execute(
            select(Ticket).where(Ticket.id == ticket_id).options(selectinload(Ticket.messages))
        )
        return r.scalar_one_or_none()

    async def load_user(self, ticket: Ticket) -> User | None:
        r = await self.session.execute(select(User).where(User.id == ticket.user_id))
        return r.scalar_one_or_none()
