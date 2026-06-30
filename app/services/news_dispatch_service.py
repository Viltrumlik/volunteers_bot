"""News broadcast: Redis queue, per-recipient locks, rate limit, retries, DLQ, delivery rows."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from app.config import get_settings
from app.database.models import NewsDeliveryStatus
from app.database.session import get_session_factory
from app.infrastructure.redis_lock import redis_lock
from app.monitoring.metrics import incr
from app.repositories.news_delivery_repository import NewsDeliveryRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.user_repository import UserRepository
from app.services.broadcast_service import parse_inline_buttons

logger = logging.getLogger(__name__)


async def enqueue_news_job(news_id: int) -> None:
    from app.infrastructure.redis_connection import get_redis

    settings = get_settings()
    r = await get_redis()
    if r is None:
        return
    await r.rpush(settings.news_queue_key, str(news_id))


async def _send_one(
    bot: Bot,
    uid: int,
    *,
    text: str | None,
    photo_file_id: str | None,
    markup: InlineKeyboardMarkup | None,
) -> None:
    if photo_file_id:
        await bot.send_photo(uid, photo_file_id, caption=text, reply_markup=markup)
    elif text:
        await bot.send_message(uid, text, reply_markup=markup)


async def _send_with_retries(
    bot: Bot,
    uid: int,
    *,
    text: str | None,
    photo_file_id: str | None,
    markup: InlineKeyboardMarkup | None,
    max_retries: int,
    base_delay: float,
) -> tuple[bool, str | None, int]:
    last_err: str | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        try:
            await _send_one(bot, uid, text=text, photo_file_id=photo_file_id, markup=markup)
            return True, None, attempts
        except TelegramAPIError as e:
            last_err = str(e)[:2000]
            if attempt >= max_retries:
                break
            delay = base_delay * (2**attempt) + random.uniform(0, 0.3)  # noqa: S311 (retry jitter, not crypto)
            await asyncio.sleep(delay)
        except Exception as e:
            last_err = str(e)[:2000]
            if attempt >= max_retries:
                break
            delay = base_delay * (2**attempt)
            await asyncio.sleep(delay)
    return False, last_err, attempts


async def _push_dlq(payload: dict[str, object]) -> None:
    from app.infrastructure.redis_connection import get_redis

    settings = get_settings()
    r = await get_redis()
    if r is None:
        return
    await r.rpush(settings.news_dlq_key, json.dumps(payload, ensure_ascii=False))


async def _throttle(min_interval: float, t0: float) -> None:
    elapsed = time.monotonic() - t0
    if elapsed < min_interval:
        await asyncio.sleep(min_interval - elapsed)


def _chunks(items: list[int], size: int) -> list[list[int]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def process_news_broadcast(bot: Bot, news_id: int) -> tuple[int, int]:
    settings = get_settings()
    factory = get_session_factory()
    text: str | None = None
    photo_file_id: str | None = None
    buttons_raw: str | None = None
    async with factory() as session:
        nrepo = NewsRepository(session)
        news = await nrepo.get(news_id)
        if not news:
            logger.warning("News job %s not found", news_id)
            return 0, 0
        text, photo_file_id, buttons_raw = news.text, news.photo_file_id, news.buttons_raw
        await nrepo.mark_sending(news_id)
        await session.commit()

    ids = await _all_user_ids()
    markup = parse_inline_buttons(buttons_raw)
    mps = max(1.0, min(25.0, settings.news_messages_per_sec))
    min_interval = 1.0 / mps
    max_retries = settings.news_max_retries
    base_delay = settings.news_retry_base_delay_sec
    batch_sz = max(1, settings.broadcast_batch_size)

    ok, fail = 0, 0
    for chunk in _chunks(ids, batch_sz):
        for uid in chunk:
            lock_key = f"volunteers_bot:lock:news:{news_id}:uid:{uid}"
            t0 = time.monotonic()
            async with redis_lock(lock_key, ttl_sec=180) as acquired:
                if not acquired:
                    logger.debug("Skip uid %s (lock held)", uid)
                    await _throttle(min_interval, t0)
                    continue

                async with factory() as session:
                    drepo = NewsDeliveryRepository(session)
                    row = await drepo.ensure_row(news_id, uid)
                    did: int = row.id
                    if row.status == NewsDeliveryStatus.sent.value:
                        await session.commit()
                        ok += 1
                        await _throttle(min_interval, t0)
                        continue
                    await session.commit()

                success, err, att = await _send_with_retries(
                    bot,
                    uid,
                    text=text,
                    photo_file_id=photo_file_id,
                    markup=markup,
                    max_retries=max_retries,
                    base_delay=base_delay,
                )

                async with factory() as session:
                    drepo = NewsDeliveryRepository(session)
                    if success:
                        await drepo.mark_sent(did)
                        ok += 1
                        await incr("news_send_ok")
                    else:
                        await drepo.mark_dead_letter(did, err or "unknown", attempts=att)
                        fail += 1
                        await incr("news_send_fail")
                        await _push_dlq(
                            {
                                "news_id": news_id,
                                "user_telegram_id": uid,
                                "error": err,
                                "attempts": att,
                            }
                        )
                    await session.commit()

            await _throttle(min_interval, t0)

    async with factory() as session:
        await NewsRepository(session).mark_completed(news_id, ok, fail)
        await session.commit()
    logger.info("News #%s completed ok=%s fail=%s", news_id, ok, fail)
    return ok, fail


async def dlq_worker_loop(_bot: Bot) -> None:
    """Drain DLQ: structured logs + metrics (optional re-queue could be added)."""
    from app.infrastructure.redis_connection import get_redis

    settings = get_settings()
    r = await get_redis()
    if r is None:
        return
    key = settings.news_dlq_key
    logger.info("DLQ monitor on %s", key)
    while True:
        raw = await r.brpop(key, timeout=120)
        if raw is None:
            continue
        _, payload_b = raw
        try:
            payload = json.loads(payload_b)
        except json.JSONDecodeError:
            logger.warning("DLQ bad json: %s", payload_b[:200])
            continue
        logger.error(
            "news_dlq",
            extra={
                "news_id": payload.get("news_id"),
                "user_telegram_id": payload.get("user_telegram_id"),
                "error": payload.get("error"),
                "attempts": payload.get("attempts"),
            },
        )
        await incr("news_dlq_processed")
        await incr("failed_news_deliveries")


async def _all_user_ids() -> list[int]:
    factory = get_session_factory()
    async with factory() as session:
        urepo = UserRepository(session)
        return await urepo.all_telegram_ids()


async def process_news_broadcast_safe(bot: Bot, news_id: int) -> tuple[int, int]:
    try:
        return await process_news_broadcast(bot, news_id)
    except Exception as e:
        logger.exception("News broadcast failed: %s", e)
        factory = get_session_factory()
        async with factory() as session:
            await NewsRepository(session).mark_failed(news_id, str(e))
            await session.commit()
        await incr("news_job_fail")
        return 0, 0


async def news_worker_loop(bot: Bot) -> None:
    from app.infrastructure.redis_connection import get_redis

    settings = get_settings()
    r = await get_redis()
    if r is None:
        logger.error("News worker: Redis required")
        return
    key = settings.news_queue_key
    logger.info("News worker listening on %s", key)
    while True:
        raw = await r.blpop(key, timeout=60)
        if raw is None:
            continue
        _, news_id_s = raw
        try:
            news_id = int(news_id_s)
        except (TypeError, ValueError):
            continue
        await process_news_broadcast_safe(bot, news_id)
