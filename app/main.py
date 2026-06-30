"""Bot entrypoint with a graceful lifecycle.

Startup fails fast if the database or Redis is unreachable. Background workers are
supervised tasks that are cancelled and drained on shutdown, and the bot session,
Redis pool, and DB engine are all closed cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from app.config import get_settings
from app.database.session import check_database, dispose_engine, init_db
from app.handlers import register_handlers
from app.infrastructure.redis_connection import check_redis, close_redis
from app.integrations.sheets_outbox import worker_loop as sheets_outbox_worker
from app.logging_config import init_sentry_if_configured, setup_logging
from app.middlewares.db_session import DbSessionMiddleware
from app.middlewares.rate_limit import RateLimitMiddleware
from app.middlewares.rbac_context import RbacContextMiddleware
from app.middlewares.user_context import UserContextMiddleware
from app.services.news_dispatch_service import dlq_worker_loop, news_worker_loop
from app.services.reminder_service import reminders_worker_loop

logger = logging.getLogger(__name__)


def _build_dispatcher() -> Dispatcher:
    settings = get_settings()
    ttl = settings.fsm_ttl_sec or None
    storage = RedisStorage.from_url(settings.redis_url, state_ttl=ttl, data_ttl=ttl)
    dp = Dispatcher(storage=storage)
    dp.update.middleware(DbSessionMiddleware())
    dp.update.middleware(UserContextMiddleware())
    dp.update.middleware(RbacContextMiddleware())
    dp.update.middleware(RateLimitMiddleware())
    register_handlers(dp)
    return dp


async def main() -> None:
    settings = get_settings()
    setup_logging(json_logs=settings.json_logs, level=settings.log_level)
    init_sentry_if_configured()

    # Fail fast on missing infrastructure rather than crashing mid-update later.
    await check_redis()
    await check_database()
    await init_db()

    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = _build_dispatcher()

    workers = [
        asyncio.create_task(news_worker_loop(bot), name="news-worker"),
        asyncio.create_task(dlq_worker_loop(bot), name="news-dlq-worker"),
        asyncio.create_task(reminders_worker_loop(bot), name="reminders-worker"),
        asyncio.create_task(sheets_outbox_worker(), name="sheets-outbox"),
    ]

    logger.info("Bot starting (long-poll)…")
    try:
        # start_polling installs SIGINT/SIGTERM handlers and returns on shutdown.
        await dp.start_polling(bot, handle_signals=True)
    finally:
        logger.info("Shutting down: cancelling workers…")
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        with contextlib.suppress(Exception):
            await bot.session.close()
        await close_redis()
        await dispose_engine()
        logger.info("Shutdown complete")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
