"""Authenticated metrics API.

* ``/health`` is unauthenticated and returns the minimum (a liveness probe).
* ``/metrics/summary`` requires a constant-time-checked ``X-API-Key`` and is
  **fail-closed**: if ``API_KEY`` is unset the endpoint returns 503 rather than
  exposing operational metrics.
* CORS is an explicit allowlist (empty by default), and a small in-process per-IP
  rate limit plus hardening headers round it out. Bind to loopback / put TLS at the proxy.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.monitoring.metrics import get_counter, pfcount_day

_RL_MAX = 30  # requests
_RL_WINDOW = 60.0  # seconds, per client IP
_hits: dict[str, deque[float]] = defaultdict(deque)


async def verify_api_key(x_api_key: str = Header(default="")) -> None:
    expected = get_settings().api_key.get_secret_value()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "metrics API key not configured")
    if not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")


async def rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    dq = _hits[ip]
    while dq and dq[0] <= now - _RL_WINDOW:
        dq.popleft()
    if len(dq) >= _RL_MAX:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limited")
    dq.append(now)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Volunteers Bot API", version="2.0.0")
    app.add_middleware(SecurityHeadersMiddleware)
    origins = settings.parsed_cors_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET"],
            allow_headers=["X-API-Key"],
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics/summary", dependencies=[Depends(rate_limit), Depends(verify_api_key)])
    async def metrics_summary() -> dict[str, int | None]:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        keys = [
            "news_send_ok",
            "news_send_fail",
            "news_job_fail",
            "news_dlq_processed",
            "failed_news_deliveries",
            "reminders_sent",
            "reminders_failed",
            "tickets_created",
            f"tickets_day:{day}",
        ]
        out: dict[str, int | None] = {k: await get_counter(k) for k in keys}
        out["approx_dau_today"] = await pfcount_day(day)
        return out

    return app


app = create_app()
