"""
app/services/template_engine.py — Jinja2-based message template engine with Redis caching.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.template import NotificationTemplate
from app.schemas.enums import Channel, NotificationType
from app.utils.logging import get_logger

logger = get_logger(__name__)

# All supported personalisation variables
ALLOWED_VARIABLES = frozenset(
    {
        "client_name",
        "master_name",
        "service_name",
        "appointment_date",
        "appointment_time",
        "salon_address",
        "salon_phone",
        "salon_name",
    }
)

# Regex to find {{variable}} placeholders
_VAR_PATTERN = re.compile(r"\{\{(\s*\w+\s*)\}\}")


@dataclass
class RenderedMessage:
    """Result of rendering a notification template."""
    text: str
    notification_type: str
    channel: str
    has_buttons: bool = True  # Most notification types include action buttons


class TemplateEngine:
    """
    Renders notification templates using Jinja2.

    - Templates are loaded from PostgreSQL and cached in Redis (TTL 5 min).
    - Missing variables are replaced with empty strings (with a WARNING log).
    - Rendering is synchronous and completes in < 100ms.
    """

    def __init__(self, db: AsyncSession, redis=None) -> None:
        self._db = db
        self._redis = redis  # Optional redis.asyncio.Redis instance
        self._jinja_env = Environment(
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        # In-process cache: {cache_key: body_template}
        self._local_cache: dict[str, str] = {}

    def _cache_key(self, notification_type: str, channel: str, language: str = "ru") -> str:
        return f"template:{notification_type}:{channel}:{language}"

    async def get_template_body(
        self,
        notification_type: str,
        channel: str,
        language: str = "ru",
    ) -> str | None:
        """
        Fetch template body from cache → DB.
        Returns None if no active template exists.
        """
        key = self._cache_key(notification_type, channel, language)

        # 1. In-process cache
        if key in self._local_cache:
            return self._local_cache[key]

        # 2. Redis cache
        if self._redis is not None:
            try:
                cached = await self._redis.get(key)
                if cached:
                    body = cached.decode() if isinstance(cached, bytes) else cached
                    self._local_cache[key] = body
                    return body
            except Exception as exc:
                logger.warning("redis_cache_read_error", error=str(exc))

        # 3. Database
        result = await self._db.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.notification_type == notification_type,
                NotificationTemplate.channel == channel,
                NotificationTemplate.language == language,
                NotificationTemplate.is_active.is_(True),
            )
        )
        template = result.scalar_one_or_none()
        if template is None:
            logger.warning(
                "template_not_found",
                notification_type=notification_type,
                channel=channel,
                language=language,
            )
            return None

        body = template.body_template
        self._local_cache[key] = body

        # Write to Redis with 5-minute TTL
        if self._redis is not None:
            try:
                await self._redis.setex(key, 300, body)
            except Exception as exc:
                logger.warning("redis_cache_write_error", error=str(exc))

        return body

    def render_body(self, body_template: str, context: dict[str, Any]) -> str:
        """
        Render a Jinja2 template body with the given context.

        Missing variables are replaced with empty strings.
        """
        # Build a safe context: fill missing allowed vars with ""
        safe_context: dict[str, Any] = {}
        for var in ALLOWED_VARIABLES:
            value = context.get(var)
            if value is None:
                logger.warning("template_variable_missing", variable=var)
                safe_context[var] = ""
            else:
                safe_context[var] = value

        # Also pass through any extra keys (future-proofing)
        for k, v in context.items():
            if k not in safe_context:
                safe_context[k] = v

        try:
            tmpl = self._jinja_env.from_string(body_template)
            return tmpl.render(**safe_context)
        except UndefinedError as exc:
            # Fallback: replace undefined vars with ""
            logger.warning("template_undefined_variable", error=str(exc))
            # Re-render with undefined replaced
            cleaned = _VAR_PATTERN.sub(
                lambda m: str(safe_context.get(m.group(1).strip(), "")),
                body_template,
            )
            return cleaned
        except Exception as exc:
            logger.error("template_render_error", error=str(exc))
            return body_template  # Return raw template as fallback

    async def render(
        self,
        notification_type: str,
        channel: str,
        context: dict[str, Any],
        language: str = "ru",
    ) -> RenderedMessage | None:
        """
        Fetch and render a template. Returns None if no template found.
        """
        body_template = await self.get_template_body(notification_type, channel, language)
        if body_template is None:
            return None

        text = self.render_body(body_template, context)

        # Buttons are shown for appointment-related notifications
        has_buttons = notification_type in {
            NotificationType.NEW_APPOINTMENT.value,
            NotificationType.CONFIRMED.value,
            NotificationType.CHANGED.value,
            NotificationType.REMINDER_24H.value,
            NotificationType.REMINDER_2H.value,
        }

        return RenderedMessage(
            text=text,
            notification_type=notification_type,
            channel=channel,
            has_buttons=has_buttons,
        )

    def validate_template(self, body_template: str) -> list[str]:
        """
        Validate a template body.
        Returns a list of invalid (unknown) variable names found in the template.
        """
        found_vars = {m.group(1).strip() for m in _VAR_PATTERN.finditer(body_template)}
        invalid = [v for v in found_vars if v not in ALLOWED_VARIABLES]

        # Also check Jinja2 syntax
        try:
            self._jinja_env.parse(body_template)
        except TemplateSyntaxError as exc:
            invalid.append(f"syntax_error: {exc.message}")

        return invalid

    async def invalidate_cache(
        self, notification_type: str, channel: str, language: str = "ru"
    ) -> None:
        """Invalidate cached template after an admin update."""
        key = self._cache_key(notification_type, channel, language)
        self._local_cache.pop(key, None)
        if self._redis is not None:
            try:
                await self._redis.delete(key)
            except Exception as exc:
                logger.warning("redis_cache_delete_error", error=str(exc))


# ── Default templates seed data ───────────────────────────────────────────────

DEFAULT_TEMPLATES: list[dict[str, str]] = [
    # ── Telegram ──────────────────────────────────────────────────────────────
    {
        "notification_type": "new_appointment",
        "channel": "telegram",
        "body_template": (
            "🎉 <b>Новая запись!</b>\n\n"
            "Здравствуйте, {{client_name}}!\n\n"
            "Вы записаны:\n"
            "📅 <b>{{appointment_date}}</b> в <b>{{appointment_time}}</b>\n"
            "💇 Услуга: {{service_name}}\n"
            "👤 Мастер: {{master_name}}\n"
            "📍 {{salon_name}}, {{salon_address}}\n\n"
            "Ждём вас! По вопросам: {{salon_phone}}"
        ),
    },
    {
        "notification_type": "confirmed",
        "channel": "telegram",
        "body_template": (
            "✅ <b>Запись подтверждена</b>\n\n"
            "{{client_name}}, ваша запись подтверждена:\n"
            "📅 {{appointment_date}} в {{appointment_time}}\n"
            "👤 Мастер: {{master_name}}\n"
            "📍 {{salon_name}}"
        ),
    },
    {
        "notification_type": "cancelled",
        "channel": "telegram",
        "body_template": (
            "❌ <b>Запись отменена</b>\n\n"
            "{{client_name}}, ваша запись на {{appointment_date}} "
            "в {{appointment_time}} отменена.\n"
            "Для новой записи: {{salon_phone}}"
        ),
    },
    {
        "notification_type": "in_progress",
        "channel": "telegram",
        "body_template": (
            "⏰ <b>Мастер ждёт вас!</b>\n\n"
            "{{client_name}}, ваш мастер {{master_name}} "
            "готов принять вас прямо сейчас.\n"
            "📍 {{salon_name}}, {{salon_address}}"
        ),
    },
    {
        "notification_type": "changed",
        "channel": "telegram",
        "body_template": (
            "🔄 <b>Изменение записи</b>\n\n"
            "{{client_name}}, ваша запись изменена:\n"
            "📅 Новая дата: <b>{{appointment_date}}</b> в <b>{{appointment_time}}</b>\n"
            "👤 Мастер: {{master_name}}\n"
            "💇 Услуга: {{service_name}}"
        ),
    },
    {
        "notification_type": "reminder_24h",
        "channel": "telegram",
        "body_template": (
            "⏰ <b>Напоминание о записи</b>\n\n"
            "{{client_name}}, напоминаем о вашей записи <b>завтра</b>:\n"
            "📅 {{appointment_date}} в {{appointment_time}}\n"
            "👤 Мастер: {{master_name}}\n"
            "📍 {{salon_name}}"
        ),
    },
    {
        "notification_type": "reminder_2h",
        "channel": "telegram",
        "body_template": (
            "🔔 <b>Скоро ваша запись!</b>\n\n"
            "{{client_name}}, через 2 часа ваша запись:\n"
            "⏰ {{appointment_time}}\n"
            "👤 Мастер: {{master_name}}\n"
            "📍 {{salon_address}}"
        ),
    },
    {
        "notification_type": "birthday",
        "channel": "telegram",
        "body_template": (
            "🎂 <b>С Днём Рождения!</b>\n\n"
            "Дорогой(ая) {{client_name}}!\n\n"
            "Команда {{salon_name}} поздравляет вас с Днём Рождения! 🎉\n"
            "Желаем здоровья, красоты и отличного настроения!\n\n"
            "Ждём вас в гости: {{salon_phone}}"
        ),
    },
    # ── WhatsApp ──────────────────────────────────────────────────────────────
    {
        "notification_type": "new_appointment",
        "channel": "whatsapp",
        "body_template": (
            "Здравствуйте, {{client_name}}! Вы записаны в {{salon_name}} "
            "на {{appointment_date}} в {{appointment_time}}. "
            "Мастер: {{master_name}}, услуга: {{service_name}}. "
            "Адрес: {{salon_address}}. Тел: {{salon_phone}}"
        ),
    },
    {
        "notification_type": "confirmed",
        "channel": "whatsapp",
        "body_template": (
            "{{client_name}}, ваша запись в {{salon_name}} подтверждена: "
            "{{appointment_date}} в {{appointment_time}}. Мастер: {{master_name}}."
        ),
    },
    {
        "notification_type": "cancelled",
        "channel": "whatsapp",
        "body_template": (
            "{{client_name}}, ваша запись в {{salon_name}} на {{appointment_date}} "
            "в {{appointment_time}} отменена. Для новой записи: {{salon_phone}}"
        ),
    },
    {
        "notification_type": "in_progress",
        "channel": "whatsapp",
        "body_template": (
            "{{client_name}}, ваш мастер {{master_name}} ждёт вас! "
            "Адрес: {{salon_address}}"
        ),
    },
    {
        "notification_type": "changed",
        "channel": "whatsapp",
        "body_template": (
            "{{client_name}}, ваша запись изменена. "
            "Новая дата: {{appointment_date}} в {{appointment_time}}. "
            "Мастер: {{master_name}}."
        ),
    },
    {
        "notification_type": "reminder_24h",
        "channel": "whatsapp",
        "body_template": (
            "Напоминаем о вашей записи в {{salon_name}} завтра, "
            "{{appointment_date}} в {{appointment_time}}. "
            "Мастер: {{master_name}}. Ждём вас!"
        ),
    },
    {
        "notification_type": "reminder_2h",
        "channel": "whatsapp",
        "body_template": (
            "{{client_name}}, через 2 часа ваша запись в {{salon_name}}: "
            "{{appointment_time}}, мастер {{master_name}}. "
            "Адрес: {{salon_address}}"
        ),
    },
    {
        "notification_type": "birthday",
        "channel": "whatsapp",
        "body_template": (
            "С Днём Рождения, {{client_name}}! "
            "Команда {{salon_name}} поздравляет вас и ждёт в гости. "
            "Тел: {{salon_phone}}"
        ),
    },
    # ── MAX ───────────────────────────────────────────────────────────────────
    {
        "notification_type": "new_appointment",
        "channel": "max",
        "body_template": (
            "🎉 **Новая запись!**\n\n"
            "Здравствуйте, {{client_name}}!\n\n"
            "Вы записаны:\n"
            "📅 **{{appointment_date}}** в **{{appointment_time}}**\n"
            "💇 Услуга: {{service_name}}\n"
            "👤 Мастер: {{master_name}}\n"
            "📍 {{salon_name}}, {{salon_address}}\n\n"
            "По вопросам: {{salon_phone}}"
        ),
    },
    {
        "notification_type": "confirmed",
        "channel": "max",
        "body_template": (
            "✅ **Запись подтверждена**\n\n"
            "{{client_name}}, ваша запись подтверждена:\n"
            "📅 {{appointment_date}} в {{appointment_time}}\n"
            "👤 Мастер: {{master_name}}"
        ),
    },
    {
        "notification_type": "cancelled",
        "channel": "max",
        "body_template": (
            "❌ **Запись отменена**\n\n"
            "{{client_name}}, ваша запись на {{appointment_date}} "
            "в {{appointment_time}} отменена.\n"
            "Для новой записи: {{salon_phone}}"
        ),
    },
    {
        "notification_type": "in_progress",
        "channel": "max",
        "body_template": (
            "⏰ **Мастер ждёт вас!**\n\n"
            "{{client_name}}, ваш мастер {{master_name}} готов принять вас.\n"
            "📍 {{salon_name}}, {{salon_address}}"
        ),
    },
    {
        "notification_type": "changed",
        "channel": "max",
        "body_template": (
            "🔄 **Изменение записи**\n\n"
            "{{client_name}}, ваша запись изменена:\n"
            "📅 **{{appointment_date}}** в **{{appointment_time}}**\n"
            "👤 Мастер: {{master_name}}"
        ),
    },
    {
        "notification_type": "reminder_24h",
        "channel": "max",
        "body_template": (
            "⏰ **Напоминание о записи**\n\n"
            "{{client_name}}, напоминаем о вашей записи **завтра**:\n"
            "📅 {{appointment_date}} в {{appointment_time}}\n"
            "👤 Мастер: {{master_name}}\n"
            "📍 {{salon_name}}"
        ),
    },
    {
        "notification_type": "reminder_2h",
        "channel": "max",
        "body_template": (
            "🔔 **Скоро ваша запись!**\n\n"
            "{{client_name}}, через 2 часа:\n"
            "⏰ {{appointment_time}}\n"
            "👤 Мастер: {{master_name}}\n"
            "📍 {{salon_address}}"
        ),
    },
    {
        "notification_type": "birthday",
        "channel": "max",
        "body_template": (
            "🎂 **С Днём Рождения!**\n\n"
            "Дорогой(ая) {{client_name}}!\n\n"
            "Команда {{salon_name}} поздравляет вас! 🎉\n"
            "Ждём вас в гости: {{salon_phone}}"
        ),
    },
]


async def seed_default_templates(db: AsyncSession) -> None:
    """Insert default templates if they don't exist yet."""
    for tmpl_data in DEFAULT_TEMPLATES:
        result = await db.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.notification_type == tmpl_data["notification_type"],
                NotificationTemplate.channel == tmpl_data["channel"],
                NotificationTemplate.language == "ru",
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            tmpl = NotificationTemplate(
                notification_type=tmpl_data["notification_type"],
                channel=tmpl_data["channel"],
                language="ru",
                body_template=tmpl_data["body_template"],
                is_active=True,
                is_default=True,
                created_by="system",
            )
            db.add(tmpl)
    await db.commit()
    logger.info("default_templates_seeded", count=len(DEFAULT_TEMPLATES))
