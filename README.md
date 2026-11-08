# Volunteers Telegram Bot

A volunteer management bot for Telegram, built with **Python 3.11+**, **aiogram 3**
and async **SQLAlchemy 2**. Volunteers register, browse and apply to projects,
read the FAQ and contact support; admins manage projects, applications, regions
and FAQ, answer support tickets from a shared admin group and send broadcasts.
The interface is available in Uzbek and Russian. SQLite is the default database
for local runs; PostgreSQL is supported via `DATABASE_URL`. Redis is required.

## Features

**For volunteers (private chat)**

- Registration with FSM: language (Uzbek / Russian), full name, age (optional),
  region (from an admin-managed list), gender, bio (optional), photo (optional)
- Projects: list active projects, view details and apply
- Profile: personal data and the status of your applications
- FAQ grouped by category, browsed with inline keyboards
- Support tickets (text, photo or other media) delivered to the admin group;
  admin replies are copied back to the volunteer
- Suggestions stored in the database and forwarded to the admin group
- Statistics: total and 7-day active users
- Language switch with `/lang` or `/language`

**For admins**

- Admin panel (`/admin`) with regions, FAQ, broadcast and — for super-admins —
  user management
- Projects: create projects (title and description)
- Applications: approve or reject pending applications
- Regions: list, add, edit and delete regions in both languages, or
  `/add_region Name (uz) | Name (ru)`
- FAQ: manage categories and questions/answers in both languages
- Broadcasts: text or photo with optional URL buttons, confirmed with `/yes`;
  queued in Redis and sent by a rate-limited background worker with retries
  and a dead-letter queue
- Support inbox in the admin group (optionally in a forum topic): reply to a
  ticket post to answer the user, `/progress_<id>` and `/close_<id>` to change
  its status
- Super-admin panel: list and search users, promote / demote admins

**Infrastructure**

- Middlewares: DB session per update, user context, role-based access, per-user
  rate limiting (Redis sliding window), creation cooldown for tickets/suggestions
- Redis-backed FSM storage, broadcast queue and metrics counters (approximate DAU)
- Alembic migrations (the app never calls `create_all`)
- Optional Google Sheets reporting (Users, Applications, Tickets tabs) through a
  background outbox
- Optional Sentry error reporting and JSON logs
- Optional FastAPI app with `/health` and `/metrics/summary`

## Bot commands

| Command | Where | Who | Description |
|---|---|---|---|
| `/start` | private | everyone | Start registration, or show the main menu |
| `/lang`, `/language` | private | registered users | Change interface language |
| `/force_start` | private | everyone | Reset a stuck conversation state |
| `/admin` | private | admins | Open the admin panel |
| `/add_region <uz> \| <ru>` | private | admins | Add a region, e.g. `/add_region Toshkent \| Ташкент` |
| `/cancel` | private | admins | Cancel project creation or a broadcast |
| `/skip` | private | admins | Skip the buttons step of a broadcast |
| `/yes` | private | admins | Confirm and send a broadcast |
| `/help` | group | everyone | Short help for group chats |
| `/volunteer_info` | group | everyone | Show the project linked to this group |
| `/link_group <name>` | group | admins | Link the group to a project (description on the next line) |
| `/progress_<id>` | admin group | admins | Mark ticket `<id>` as in progress |
| `/close_<id>` | admin group | admins | Close ticket `<id>` |

Most volunteer and admin actions are reply-keyboard buttons in the main menu
rather than slash commands.

## Tech stack

- Python 3.11+, [aiogram 3](https://docs.aiogram.dev/) (long polling)
- SQLAlchemy 2 (async) with aiosqlite or asyncpg, Alembic
- Redis (`redis-py` asyncio)
- pydantic-settings for configuration
- Optional: gspread + google-auth, sentry-sdk, FastAPI + Uvicorn

## Getting started

### Prerequisites

- Python 3.11 or newer
- A running Redis server
- A bot token from [@BotFather](https://t.me/BotFather)
- A Telegram group (or supergroup) for admins, with the bot added as a member
- Optional: PostgreSQL

### Install

```bash
git clone https://github.com/Viltrumlik/volunteers_bot.git
cd volunteers_bot
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Required variables:

| Variable | Example | Description |
|---|---|---|
| `BOT_TOKEN` | `123456:ABC-DEF...` | Bot token from @BotFather |
| `ADMIN_GROUP_ID` | `-1001234567890` | Chat id of the admin group that receives tickets and suggestions |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection (FSM, rate limits, queues, metrics) |
| `ADMIN_IDS` | `111111111,222222222` | Comma-separated Telegram user ids of admins |

Optional variables:

| Variable | Default | Description |
|---|---|---|
| `SUPER_ADMIN_IDS` | empty | Super-admins; if empty, every `ADMIN_IDS` entry is a super-admin |
| `ADMIN_TICKET_TOPIC_ID` | empty | Forum topic id in the admin group for tickets |
| `DATABASE_URL` | `sqlite+aiosqlite:///./volunteers_bot.db` | e.g. `postgresql://user:password@localhost:5432/volunteers` (rewritten to `postgresql+asyncpg://`) |
| `NEWS_QUEUE_KEY` / `NEWS_DLQ_KEY` | `volunteers_bot:news_queue` / `volunteers_bot:news_dlq` | Redis keys for the broadcast queue and dead-letter queue |
| `FSM_REDIS_KEY_PREFIX` | `fsm` | Redis key prefix for FSM storage |
| `NEWS_MESSAGES_PER_SEC` | `25` | Broadcast worker send rate |
| `NEWS_MAX_RETRIES` / `NEWS_RETRY_BASE_DELAY_SEC` | `3` / `0.5` | Broadcast retry policy |
| `BROADCAST_BATCH_SIZE` / `BROADCAST_DELAY_SEC` | `25` / `0.05` | Batching for direct sends |
| `RATE_LIMIT_MESSAGES` / `RATE_LIMIT_WINDOW_SEC` | `20` / `60` | Per-user message rate limit |
| `CREATION_COOLDOWN_SEC` | `45` | Seconds between new tickets or suggestions per user (`0` disables) |
| `JSON_LOGS` / `LOG_LEVEL` | `0` / `INFO` | Logging format and level |
| `SENTRY_DSN` | empty | Enables Sentry when set |
| `GOOGLE_CREDENTIALS_PATH` / `GOOGLE_SHEET_ID` | empty | Enables Google Sheets reporting when both are set |

`.env` is gitignored — keep real tokens out of the repository.

For Google Sheets: enable the Sheets API in Google Cloud, create a service
account, download its JSON key, and share the spreadsheet with the service
account email as Editor.

### Create the database schema

Tables are created only by Alembic:

```bash
alembic upgrade head
```

`schema.sql` is a reference copy of the DDL; the SQLAlchemy models and the
migrations are the source of truth.

### Run

```bash
python -m app.main
```

Optional HTTP API (health check and Redis metrics), as a separate process:

```bash
uvicorn app.api.main:app --host 127.0.0.1 --port 8080
```

### Admin group setup

- Add the bot to the admin group. If admins should be able to answer tickets by
  replying, disable privacy mode in @BotFather (`/setprivacy` → Disable) so the
  bot sees those replies.
- Ticket and suggestion posts include the user's id, name and username.
- Reply to the bot's ticket post (or anywhere in that reply thread) to send a
  message to the volunteer.

### Roles

- **user** — default after registration
- **admin** — projects, applications, regions, FAQ, broadcasts, `/link_group`
- **super_admin** — everything above plus the user management panel

Users listed in `ADMIN_IDS` / `SUPER_ADMIN_IDS` keep at least that role on every
update, even if the database says otherwise.

### Production notes

- Run under a process manager (systemd, Docker, ...) with one bot instance per token.
- Run `alembic upgrade head` on every deploy before starting the bot.
- Tune the `NEWS_*`, `BROADCAST_*`, `RATE_LIMIT_*` and `CREATION_COOLDOWN_SEC`
  values for Telegram's limits and your audience size.

## Project structure

```
app/
  main.py              entry point: bot, dispatcher, middlewares, background workers
  config.py            settings (pydantic-settings, .env)
  handlers/            routers: user/, admin/, emergency.py (high-priority commands)
  services/            business logic (users, projects, tickets, broadcasts, ...)
  repositories/        database queries
  database/            models, async session, bootstrap data
  middlewares/         DB session, user context, RBAC, rate limiting
  keyboards/           reply and inline keyboards
  states/              FSM state groups
  locales/             uz.json, ru.json
  integrations/        Google Sheets service and outbox
  infrastructure/      Redis connection and lock
  monitoring/          Redis counters
  api/                 optional FastAPI app
  security/, utils/    RBAC helpers, validation, formatting
migrations/            Alembic environment and versions
schema.sql             reference DDL
alembic.ini
requirements.txt
.env.example
```

## License

Released under the [MIT License](LICENSE).
