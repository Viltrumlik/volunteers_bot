"""Serialize Google Sheets API calls — bounded queue, batched drain, non-blocking handlers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_queue: asyncio.Queue[Callable[[], Awaitable[None]]] = asyncio.Queue(maxsize=1000)


async def enqueue(coro_factory: Callable[[], Awaitable[None]]) -> None:
    try:
        _queue.put_nowait(coro_factory)
    except asyncio.QueueFull:
        from app.monitoring.metrics import incr

        logger.warning("Sheets outbox full (size=%s); dropping write", _queue.maxsize)
        await incr("sheets_outbox_dropped")


async def worker_loop() -> None:
    while True:
        first = await _queue.get()
        batch: list[Callable[[], Awaitable[None]]] = [first]
        while len(batch) < 25:
            try:
                batch.append(_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        for fn in batch:
            try:
                await fn()
            except Exception:
                logger.exception("Sheets outbox batch item failed")
