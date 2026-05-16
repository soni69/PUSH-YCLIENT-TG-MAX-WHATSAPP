"""
app/config.py — Application configuration via Pydantic Settings.

All settings are loaded from environment variables (or .env file).
Missing required variables cause a ValidationError at startup, which
is caught in app/main.py and results in exit code 1.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration object.

    All fields without a default value are *required* — the application
    will refuse to start if they are absent from the environment.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── YClients ──────────────────────────────────────────────────────────────
    yclients_api_token: str = Field(
        ...,
        description="Bearer-токен авторизации YClients API",
    )
    yclients_company_id: int = Field(
        ...,
        description="ID компании в YClients",
    )
    yclients_webhook_secret: str = Field(
        ...,
        description="Секретный ключ для валидации HMAC-подписи webhook YClients",
    )

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(
        ...,
        description="Токен Telegram-бота (от @BotFather)",
    )

    # ── WhatsApp Business Cloud API ───────────────────────────────────────────
    whatsapp_api_token: str = Field(
        ...,
        description="Bearer-токен WhatsApp Business Cloud API (Graph API)",
    )
    whatsapp_phone_number_id: str = Field(
        ...,
        description="ID номера телефона бизнеса в WhatsApp",
    )
    whatsapp_business_account_id: str = Field(
        ...,
        description="ID бизнес-аккаунта WhatsApp",
    )
    whatsapp_verify_token: str = Field(
        ...,
        description="Токен верификации webhook WhatsApp",
    )

    # ── MAX Bot API ───────────────────────────────────────────────────────────
    max_bot_token: str = Field(
        ...,
        description="Токен бота MAX (platform-api.max.ru)",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        ...,
        description=(
            "Async PostgreSQL DSN, например: "
            "postgresql+asyncpg://user:password@localhost:5432/dbname"
        ),
    )
    db_pool_min_size: int = Field(
        default=5,
        ge=1,
        description="Минимальный размер пула соединений SQLAlchemy",
    )
    db_pool_max_size: int = Field(
        default=20,
        ge=1,
        description="Максимальный размер пула соединений SQLAlchemy",
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(
        ...,
        description="Redis DSN, например: redis://localhost:6379/0",
    )

    # ── Admin panel ───────────────────────────────────────────────────────────
    admin_username: str = Field(
        ...,
        description="Логин администратора для AdminPanel",
    )
    admin_password: str = Field(
        ...,
        description="Пароль администратора для AdminPanel (хранится в хешированном виде)",
    )
    admin_jwt_secret: str = Field(
        ...,
        description="Секретный ключ для подписи JWT-токенов AdminPanel",
    )
    admin_jwt_expire_minutes: int = Field(
        default=60,
        ge=1,
        description="Время жизни JWT-токена AdminPanel в минутах",
    )

    # ── Scheduler / polling ───────────────────────────────────────────────────
    polling_interval_seconds: int = Field(
        default=120,
        ge=60,
        le=180,
        description="Интервал опроса YClients API в секундах (60–180)",
    )

    # ── Localisation ──────────────────────────────────────────────────────────
    timezone: str = Field(
        default="Europe/Moscow",
        description="Часовой пояс организации (IANA timezone name)",
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Уровень логирования (DEBUG | INFO | WARNING | ERROR | CRITICAL)",
    )

    # ── Environment ───────────────────────────────────────────────────────────
    environment: Literal["development", "staging", "production"] = Field(
        default="production",
        description="Окружение запуска (development | staging | production)",
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    webhook_rate_limit: str = Field(
        default="100/minute",
        description=(
            "Ограничение частоты запросов к /webhook/yclients "
            "в формате slowapi, например: '100/minute'"
        ),
    )

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure the DSN uses the asyncpg driver."""
        if not v.startswith(("postgresql+asyncpg://", "postgresql://", "postgres://")):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL DSN "
                "(e.g. postgresql+asyncpg://user:pass@host/db)"
            )
        # Normalise plain postgres:// → postgresql+asyncpg://
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://") and "+asyncpg" not in v:
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        """Ensure the URL uses the redis:// or rediss:// scheme."""
        if not v.startswith(("redis://", "rediss://")):
            raise ValueError(
                "REDIS_URL must start with redis:// or rediss://"
            )
        return v

    @model_validator(mode="after")
    def validate_pool_sizes(self) -> "Settings":
        """Ensure min pool size does not exceed max pool size."""
        if self.db_pool_min_size > self.db_pool_max_size:
            raise ValueError(
                f"DB_POOL_MIN_SIZE ({self.db_pool_min_size}) must be <= "
                f"DB_POOL_MAX_SIZE ({self.db_pool_max_size})"
            )
        return self

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def whatsapp_api_url(self) -> str:
        return (
            f"https://graph.facebook.com/v18.0/"
            f"{self.whatsapp_phone_number_id}/messages"
        )

    @property
    def max_api_base_url(self) -> str:
        return "https://botapi.max.ru"

    @property
    def yclients_api_base_url(self) -> str:
        return "https://api.yclients.com/api/v1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    Using @lru_cache ensures the .env file is read only once per process.
    Call ``get_settings.cache_clear()`` in tests to reload settings.
    """
    return Settings()
