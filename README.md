# Volunteers Telegram Bot

A hardened, fully-tested volunteer-management Telegram bot built with **Python 3.12**,
**aiogram 3**, and **SQLAlchemy 2** (async). PostgreSQL is recommended for production
(`DATABASE_URL`); SQLite is the default for local runs. Redis is required (FSM, rate limits,
cooldowns, queues, metrics).

## Features

- **Registration** (name, contact, age, region, gender, bio, photo) via an FSM.
- **FAQ** stored in the DB; admins add/edit/delete; users browse via inline keyboards (uz/ru).
- **Support tickets**: user messages reach an admin group; admins reply to the bot's post to
  answer the user; `/close_<id>` / `/progress_<id>` manage state.
- **Broadcasts** (text or photo, optional URL buttons) via a Redis-queued worker with retries,
  rate limiting, idempotent per-recipient delivery rows, and a dead-letter queue.
- **Suggestions** stored in the DB and forwarded to the admin group.
- **Projects & applications**: users apply, admins approve/reject (auto-promotes to `volunteer`).
- **Shift Scheduling + Hours Tracking** (the signature feature — see below).
- **Group commands**: `/help`, `/volunteer_info`, `/link_group` (bot admins).
- **Super-admin panel**: search users, change roles (env super-admins are protected).
- **RBAC** (`user` / `volunteer` / `admin` / `super_admin`), uz/ru i18n, per-user rate limiting,
  cross-worker anti-spam cooldowns, audit logging, structured logging with secret/PII redaction.

### Shift Scheduling + Hours

- Admins create timezone-aware **shifts** with a capacity; volunteers **browse, sign up /
  waitlist / cancel, and check in / out** within a configurable window.
- Capacity is **race-free** (row lock on the event + a `UNIQUE(event, user)` backstop); cancelling
  a confirmed spot **auto-promotes the waitlist head** (notified after commit).
- Hours are computed from check-in/out into an **append-only ledger** (clamped to the shift,
  capped at the scheduled duration), idempotent so a double check-out can't double-credit.
- A Redis **reminder worker** sends 24h / 1h-before and check-out-nudge reminders **at most once**
  (a ZSET due-queue + idempotent reminder rows + a fence-token lock), and sweeps no-shows.
- **"My hours"** summary and an all-time / 30-day **leaderboard**.

## Architecture

Layered: `handlers → services → repositories → SQLAlchemy models`, with Redis-backed FSM and
middleware for DB session, user context, RBAC, rate limiting.

```
app/
  config.py            # pydantic-settings v2 (SecretStr), validators, startup checks
  main.py              # graceful lifecycle: startup probes, supervised workers, clean shutdown
  logging_config.py    # structured logs + secret/PII redaction; Sentry scrubber
  i18n.py              # uz/ru JSON loader (+ key-parity helpers for tests)
  database/            # base (naming convention), engine/session, models, bootstrap
  repositories/        # data access (row locks, idempotent upserts, leaderboard aggregation)
  services/            # business logic (incl. event/signup/attendance/hours/reminder + audit)
  handlers/ user|admin # routers (commands, callbacks, FSM); shifts/hours/events/attendance
  keyboards/           # static + shift inline keyboards
  middlewares/         # db_session, user_context, rbac, rate_limit
  infrastructure/      # redis connection, fenced locks, Redis cooldown, atomic rate limiter
  integrations/        # Google Sheets (inline-JSON creds) + bounded outbox
  monitoring/          # Redis counters / HyperLogLog DAU
  api/                 # authenticated FastAPI metrics service
  locales/             # uz.json, ru.json
migrations/            # Alembic (env-driven URL); 0001 greenfield baseline
tests/                 # pytest-asyncio: unit + integration + security regression
```

## Setup

### Option A — Docker (recommended)

```bash
cp .env.example .env      # fill BOT_TOKEN, ADMIN_IDS, ADMIN_GROUP_ID, POSTGRES_PASSWORD
docker compose up --build -d
```

This starts Postgres + Redis, runs `alembic upgrade head`, then the bot.

### Option B — local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: pip install -r requirements.txt
cp .env.example .env             # fill in the required values
alembic upgrade head             # apply the schema (tables are not created at startup)
python -m app.main               # run the bot (long-poll)
```

Required env: `BOT_TOKEN`, `ADMIN_IDS`, `ADMIN_GROUP_ID`, `REDIS_URL`. See `.env.example` for the
full list (broadcast/rate-limit/shift/reminder tuning, Google Sheets, the metrics API key, etc.).

## Metrics API (optional)

```bash
API_KEY=$(openssl rand -hex 24)   # set in .env
uvicorn app.api.main:app --host 127.0.0.1 --port 8080
```

`/health` is unauthenticated; `/metrics/summary` requires `X-API-Key` (constant-time checked,
**fail-closed** if no key is configured), is per-IP rate-limited, and sends hardening headers.
Bind to loopback and terminate TLS at a reverse proxy.

## Development & quality gate

```bash
make check     # ruff (lint+format), mypy --strict, pytest+coverage, bandit, pip-audit
make cov       # tests with the 80% coverage gate (core logic packages)
make fmt       # auto-format + fix
```

CI (`.github/workflows/ci.yml`) runs the same gate plus a Docker build. mypy is strict on the
business-logic core; the aiogram presentation layer (handlers/keyboards/middlewares) is checked
leniently because of dynamically-injected handler kwargs. Coverage is gated on
services/repositories/infrastructure/utils/security (the Redis+Telegram worker glue is exercised
by an integration test rather than line-counted).

## Security notes

- Secrets (`BOT_TOKEN`, `SENTRY_DSN`, `API_KEY`, Google creds) are `SecretStr` and never logged;
  a logging filter scrubs token-shaped strings and masks Telegram IDs.
- Distributed locks use a UUID fence token + Lua compare-and-delete; the reminder scheduler lock
  **fails closed**. Cooldowns and the rate limiter are atomic Redis operations (cross-worker safe).
- Admin/super-admin mutations are written to an **audit log**; broadcast button URLs are restricted
  to an `https`/`tg` allowlist with internal-host blocking.
- The DB schema enforces enum `CHECK` constraints, unique/partial-unique idempotency, and FKs.
- Google service-account credentials can be supplied as an **inline JSON env var** (secret manager)
  instead of an on-disk path.
- Run `pip-audit` periodically and bump `aiogram` / `fastapi` to clear transitive CVEs behind their
  current version pins.

## Roles

- **user** — default after registration.
- **volunteer** — granted on application approval; can use shifts, check-in/out, hours.
- **admin** — FAQ, regions, broadcasts, applications, shifts/attendance, `/link_group`.
- **super_admin** — user-management panel and role assignment.

Env-listed `ADMIN_IDS` / `SUPER_ADMIN_IDS` are merged on each update so configured operators keep
at least their env-assigned role (and env super-admins cannot be demoted).

## License

MIT — see [LICENSE](LICENSE).
