"""SQLAlchemy 2 typed models (greenfield schema).

Conventions:
* Enum-like columns are stored as ``str`` ``.value`` plus a DB ``CHECK`` constraint
  enumerating the allowed values (portable across SQLite/Postgres, unlike native enums).
* All timestamps are tz-aware (``DateTime(timezone=True)``), defaulting to ``func.now()``.
* Idempotency/uniqueness is enforced at the DB level (UNIQUE / partial-unique indexes).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def _enum_check(column: str, values: type[enum.Enum], name: str) -> CheckConstraint:
    allowed = ", ".join(f"'{m.value}'" for m in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class UserRole(str, enum.Enum):
    user = "user"
    volunteer = "volunteer"
    admin = "admin"
    super_admin = "super_admin"


class Gender(str, enum.Enum):
    female = "female"
    male = "male"
    other = "other"
    unspecified = "unspecified"


class ApplicationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    closed = "closed"


class TicketPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class NewsStatus(str, enum.Enum):
    pending = "pending"
    sending = "sending"
    completed = "completed"
    failed = "failed"


class NewsDeliveryStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    dead_letter = "dead_letter"


class EventStatus(str, enum.Enum):
    open = "open"
    closed = "closed"
    cancelled = "cancelled"


class SignupStatus(str, enum.Enum):
    registered = "registered"
    waitlisted = "waitlisted"
    cancelled = "cancelled"
    checked_in = "checked_in"
    checked_out = "checked_out"
    no_show = "no_show"


class ReminderKind(str, enum.Enum):
    t24h = "t24h"
    t1h = "t1h"
    checkout_nudge = "checkout_nudge"


class ReminderStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    skipped = "skipped"
    failed = "failed"
    dead_letter = "dead_letter"


class LedgerSource(str, enum.Enum):
    auto = "auto"
    admin_adjust = "admin_adjust"


# ---------------------------------------------------------------------------
# Reference / lookup tables
# ---------------------------------------------------------------------------
class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_uz: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="region")


class FAQCategory(Base):
    __tablename__ = "faq_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_uz: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    faqs: Mapped[list[FAQ]] = relationship(back_populates="category")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        _enum_check("role", UserRole, "role"),
        Index("ix_users_role", "role"),
        Index("ix_users_region_id", "region_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True, default="")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(32), default=UserRole.user.value, nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="uz", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "registered_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    region: Mapped[Region | None] = relationship(back_populates="users")
    tickets: Mapped[list[Ticket]] = relationship(
        back_populates="user", foreign_keys="Ticket.user_id"
    )
    suggestions: Mapped[list[Suggestion]] = relationship(back_populates="user")
    applications: Mapped[list[Application]] = relationship(back_populates="user")
    signups: Mapped[list[EventSignup]] = relationship(back_populates="user")


# ---------------------------------------------------------------------------
# FAQ / projects / applications
# ---------------------------------------------------------------------------
class FAQ(Base):
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("faq_categories.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    question_uz: Mapped[str] = mapped_column(String(512), nullable=False)
    answer_uz: Mapped[str] = mapped_column(Text, nullable=False)
    question_ru: Mapped[str | None] = mapped_column(String(512), nullable=True)
    answer_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    category: Mapped[FAQCategory] = relationship(back_populates="faqs")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_is_active", "is_active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    applications: Mapped[list[Application]] = relationship(back_populates="project")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_applications_user_project"),
        _enum_check("status", ApplicationStatus, "status"),
        Index("ix_applications_user_id", "user_id"),
        Index("ix_applications_project_id", "project_id"),
        Index("ix_applications_status", "status"),
        Index("ix_applications_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ApplicationStatus.pending.value, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="applications")
    user: Mapped[User] = relationship(back_populates="applications")


# ---------------------------------------------------------------------------
# Broadcasts
# ---------------------------------------------------------------------------
class News(Base):
    """Broadcast job: queued in Redis, progress persisted here."""

    __tablename__ = "news"
    __table_args__ = (_enum_check("status", NewsStatus, "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    buttons_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=NewsStatus.pending.value, nullable=False
    )
    sent_ok: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_fail: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NewsDelivery(Base):
    """Per-recipient outcome for a broadcast (idempotent per news + telegram user)."""

    __tablename__ = "news_deliveries"
    __table_args__ = (
        UniqueConstraint("news_id", "user_telegram_id", name="uq_news_delivery_recipient"),
        _enum_check("status", NewsDeliveryStatus, "status"),
        Index("ix_news_deliveries_news_id", "news_id"),
        Index("ix_news_deliveries_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news.id", ondelete="CASCADE"), nullable=False)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(24), default=NewsDeliveryStatus.pending.value, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Support tickets
# ---------------------------------------------------------------------------
class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        _enum_check("status", TicketStatus, "status"),
        _enum_check("priority", TicketPriority, "priority"),
        Index("ix_tickets_user_id", "user_id"),
        Index("ix_tickets_status", "status"),
        Index("ix_tickets_priority", "priority"),
        Index("ix_tickets_assigned", "assigned_telegram_id"),
        Index("ix_tickets_status_priority", "status", "priority"),
        Index("ix_tickets_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=TicketStatus.open.value, nullable=False)
    priority: Mapped[str] = mapped_column(
        String(16), default=TicketPriority.medium.value, nullable=False
    )
    ticket_type: Mapped[str] = mapped_column(String(32), default="help", nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    admin_thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="tickets", foreign_keys=[user_id])
    messages: Mapped[list[TicketMessage]] = relationship(
        back_populates="ticket", order_by="TicketMessage.created_at"
    )


class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    __table_args__ = (Index("ix_ticket_messages_ticket_id", "ticket_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped[Ticket] = relationship(back_populates="messages")


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="suggestions")


class LinkedGroup(Base):
    __tablename__ = "linked_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Shift scheduling + hours (signature feature)
# ---------------------------------------------------------------------------
class Event(Base):
    """A shift volunteers can sign up for. ``signup_count`` is the lock target."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="time_order"),
        CheckConstraint("capacity > 0", name="capacity_pos"),
        CheckConstraint("signup_count >= 0 AND signup_count <= capacity", name="count_bounds"),
        CheckConstraint("waitlist_count >= 0", name="waitlist_nonneg"),
        _enum_check("status", EventStatus, "status"),
        Index("ix_events_status_starts", "status", "starts_at"),
        Index("ix_events_starts_at", "starts_at"),
        Index("ix_events_region_id", "region_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    location: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=True
    )
    tz: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent", nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    signup_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    waitlist_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=EventStatus.open.value, nullable=False)
    checkin_opens_min_before: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    checkin_closes_min_after: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    no_show_grace_min: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    signups: Mapped[list[EventSignup]] = relationship(back_populates="event")


class EventSignup(Base):
    __tablename__ = "event_signups"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_event_signups_event_user"),
        _enum_check("status", SignupStatus, "status"),
        Index("ix_event_signups_event_status", "event_id", "status"),
        Index("ix_event_signups_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=SignupStatus.registered.value, nullable=False
    )
    waitlist_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    event: Mapped[Event] = relationship(back_populates="signups")
    user: Mapped[User] = relationship(back_populates="signups")


class HoursLedger(Base):
    """Append-only hours ledger. Total hours = SUM(minutes). Never mutated in place."""

    __tablename__ = "hours_ledger"
    __table_args__ = (
        _enum_check("source", LedgerSource, "source"),
        # At most one auto entry per signup → double check-out / worker re-run can't double-credit.
        Index(
            "uq_hours_ledger_signup_auto",
            "signup_id",
            unique=True,
            sqlite_where=text("source = 'auto'"),
            postgresql_where=text("source = 'auto'"),
        ),
        Index("ix_hours_ledger_user_id", "user_id"),
        Index("ix_hours_ledger_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    signup_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_signups.id", ondelete="SET NULL"), nullable=True
    )
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EventReminder(Base):
    """Idempotent reminder-delivery row (analog of NewsDelivery): at most once per kind."""

    __tablename__ = "event_reminders"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", "kind", name="uq_event_reminders_event_user_kind"),
        _enum_check("kind", ReminderKind, "kind"),
        _enum_check("status", ReminderStatus, "status"),
        Index("ix_event_reminders_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ReminderStatus.pending.value, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Audit log (admin / super-admin mutations)
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_actor", "actor_telegram_id"),
        Index("ix_audit_log_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
