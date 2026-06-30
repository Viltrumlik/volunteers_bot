"""Async SQLAlchemy engine + session factory.

Schema changes happen only via Alembic (no ``create_all`` at startup).
The URL is normalized once in :meth:`Settings.normalized_database_url`.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Exposed for Alembic / health checks."""
    get_session_factory()
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        url = get_settings().normalized_database_url()
        connect_args: dict[str, object] = {}
        pool_kwargs: dict[str, object] = {}
        if "sqlite" in url:
            connect_args["check_same_thread"] = False
        if "postgresql" in url:
            pool_kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)
        _engine = create_async_engine(url, echo=False, connect_args=connect_args, **pool_kwargs)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
        logger.info("Database engine created (scheme=%s)", url.split(":", 1)[0])
    return _session_factory


async def check_database() -> None:
    """Fail-fast connectivity probe used at startup."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SELECT 1"))


async def init_db() -> None:
    """Seed bootstrap defaults. Tables must already exist (``alembic upgrade head``)."""
    factory = get_session_factory()
    async with factory() as session:
        from app.database.bootstrap import bootstrap_defaults

        await bootstrap_defaults(session)
        await session.commit()
    logger.info("Database bootstrap completed (migrations applied separately)")


async def dispose_engine() -> None:
    """Close the connection pool on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed")
    _engine = None
    _session_factory = None
