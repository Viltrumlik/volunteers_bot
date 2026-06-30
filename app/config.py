"""Application settings (pydantic-settings v2).

Secrets are typed as ``SecretStr`` so they never appear in ``repr``/tracebacks/logs.
The database URL is normalized to the async driver in exactly one place
(:meth:`Settings.normalized_database_url`) so the app and Alembic agree.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram ----------------------------------------------------------
    bot_token: SecretStr = Field(..., validation_alias="BOT_TOKEN")
    admin_ids: str = Field(default="", validation_alias="ADMIN_IDS")
    super_admin_ids: str = Field(default="", validation_alias="SUPER_ADMIN_IDS")
    admin_group_id: int = Field(..., validation_alias="ADMIN_GROUP_ID")
    admin_ticket_topic_id: int | None = Field(
        default=None, validation_alias="ADMIN_TICKET_TOPIC_ID"
    )

    # --- Database ----------------------------------------------------------
    database_url: str = Field(
        default="sqlite+aiosqlite:///./volunteers_bot.db",
        validation_alias="DATABASE_URL",
    )

    # --- Redis (required) --------------------------------------------------
    redis_url: str = Field(..., min_length=1, validation_alias="REDIS_URL")
    news_queue_key: str = Field("volunteers_bot:news_queue", validation_alias="NEWS_QUEUE_KEY")
    news_dlq_key: str = Field("volunteers_bot:news_dlq", validation_alias="NEWS_DLQ_KEY")
    fsm_redis_key_prefix: str = Field("fsm", validation_alias="FSM_REDIS_KEY_PREFIX")
    fsm_ttl_sec: int = Field(86400, ge=0, validation_alias="FSM_TTL_SEC")

    # --- Broadcast / news worker ------------------------------------------
    broadcast_batch_size: int = Field(25, ge=1, validation_alias="BROADCAST_BATCH_SIZE")
    broadcast_delay_sec: float = Field(0.05, ge=0, validation_alias="BROADCAST_DELAY_SEC")
    news_messages_per_sec: float = Field(25.0, gt=0, validation_alias="NEWS_MESSAGES_PER_SEC")
    news_max_retries: int = Field(3, ge=0, validation_alias="NEWS_MAX_RETRIES")
    news_retry_base_delay_sec: float = Field(
        0.5, ge=0, validation_alias="NEWS_RETRY_BASE_DELAY_SEC"
    )

    # --- Rate limiting & anti-spam ----------------------------------------
    rate_limit_messages: int = Field(20, ge=1, validation_alias="RATE_LIMIT_MESSAGES")
    rate_limit_window_sec: int = Field(60, ge=1, validation_alias="RATE_LIMIT_WINDOW_SEC")
    creation_cooldown_sec: float = Field(45.0, ge=0, validation_alias="CREATION_COOLDOWN_SEC")

    # --- Shift scheduling + reminders -------------------------------------
    default_event_tz: str = Field("Asia/Tashkent", validation_alias="DEFAULT_EVENT_TZ")
    reminders_due_key: str = Field(
        "volunteers_bot:reminders:due", validation_alias="REMINDERS_DUE_KEY"
    )
    reminders_dlq_key: str = Field(
        "volunteers_bot:reminders:dlq", validation_alias="REMINDERS_DLQ_KEY"
    )
    reminders_poll_interval_sec: int = Field(
        30, ge=1, validation_alias="REMINDERS_POLL_INTERVAL_SEC"
    )
    checkout_nudge_delay_min: int = Field(15, ge=0, validation_alias="CHECKOUT_NUDGE_DELAY_MIN")
    leaderboard_size: int = Field(10, ge=1, le=50, validation_alias="LEADERBOARD_SIZE")

    # --- Observability -----------------------------------------------------
    json_logs: bool = Field(False, validation_alias="JSON_LOGS")
    log_level: str = Field("INFO", validation_alias="LOG_LEVEL")
    sentry_dsn: SecretStr = Field(default=SecretStr(""), validation_alias="SENTRY_DSN")
    log_hash_salt: SecretStr = Field(default=SecretStr(""), validation_alias="LOG_HASH_SALT")

    # --- Google Sheets (optional) -----------------------------------------
    google_credentials_path: str = Field("", validation_alias="GOOGLE_CREDENTIALS_PATH")
    google_credentials_json: SecretStr = Field(
        default=SecretStr(""), validation_alias="GOOGLE_CREDENTIALS_JSON"
    )
    google_sheet_id: str = Field("", validation_alias="GOOGLE_SHEET_ID")

    # --- Optional REST metrics API ----------------------------------------
    api_host: str = Field("127.0.0.1", validation_alias="API_HOST")
    api_port: int = Field(8080, validation_alias="API_PORT")
    api_enable: bool = Field(False, validation_alias="API_ENABLE")
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="API_KEY")
    api_cors_origins: str = Field("", validation_alias="API_CORS_ORIGINS")

    # --- Validators --------------------------------------------------------
    @field_validator("admin_group_id", mode="before")
    @classmethod
    def _parse_admin_group(cls, v: object) -> int:
        if v is None or v == "":
            raise ValueError("ADMIN_GROUP_ID is required")
        return int(str(v))

    @field_validator("admin_ticket_topic_id", mode="before")
    @classmethod
    def _parse_ticket_topic(cls, v: object) -> int | None:
        if v is None or v == "":
            return None
        return int(str(v))

    @field_validator("default_event_tz")
    @classmethod
    def _validate_tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"DEFAULT_EVENT_TZ is not a valid IANA timezone: {v!r}") from exc
        return v

    # --- Derived helpers ---------------------------------------------------
    def parsed_admin_ids(self) -> set[int]:
        return self._parse_id_set(self.admin_ids)

    def parsed_super_admin_ids(self) -> set[int]:
        base = self._parse_id_set(self.super_admin_ids)
        return base or self._parse_id_set(self.admin_ids)

    def is_env_privileged_user(self, telegram_id: int) -> bool:
        return (
            telegram_id in self.parsed_admin_ids() or telegram_id in self.parsed_super_admin_ids()
        )

    def parsed_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    def normalized_database_url(self) -> str:
        """Return the DATABASE_URL rewritten to an async driver (single source of truth)."""
        url = self.database_url
        if url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + url[len("postgresql://") :]
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url[len("postgres://") :]
        return url

    @staticmethod
    def _parse_id_set(raw: str) -> set[int]:
        out: set[int] = set()
        for part in (raw or "").split(","):
            part = part.strip()
            if part:
                out.add(int(part))
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
