"""
app/adapters/telegram_adapter.py — Telegram Bot API adapter using aiogram 3.x.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.adapters.base import BaseAdapter
from app.config import get_settings
from app.schemas.enums import Channel, DeliveryStatus
from app.schemas.notification import DeliveryResult
from app.services.template_engine import RenderedMessage
from app.utils.logging import get_logger
from app.utils.rate_limiter import get_telegram_rate_limiter

logger = get_logger(__name__)

HELP_TEXT = (
    "Доступные команды:\n"
    "/start — начать работу с ботом\n"
    "/unsubscribe — отписаться от уведомлений\n"
    "/help — показать эту справку\n\n"
    "Для изменения записи позвоните в салон."
)


class TelegramAdapter(BaseAdapter):
    """
    Sends notifications via Telegram Bot API.

    Features:
    - HTML parse mode
    - Inline keyboard with Confirm / Cancel / Reschedule buttons
    - Handles 403 Forbidden (bot blocked) → deactivates channel
    - Respects retry_after on 429
    - Token bucket rate limiting (30/s global, 1/s per chat)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._bot = Bot(
            token=settings.telegram_bot_token,
            parse_mode=ParseMode.HTML,
        )
        self._rate_limiter = get_telegram_rate_limiter()
        self._router = Router()
        self._dispatcher = Dispatcher()
        self._dispatcher.include_router(self._router)
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Register message and callback handlers."""

        @self._router.message(Command("start"))
        async def cmd_start(message: Message) -> None:
            await self._handle_start(message)

        @self._router.message(Command("unsubscribe"))
        async def cmd_unsubscribe(message: Message) -> None:
            await self._handle_unsubscribe(message)

        @self._router.message(Command("help"))
        async def cmd_help(message: Message) -> None:
            await message.answer(HELP_TEXT)

        @self._router.message()
        async def handle_text(message: Message) -> None:
            await message.answer(HELP_TEXT)

        @self._router.callback_query()
        async def handle_callback(callback: CallbackQuery) -> None:
            await self._handle_callback(callback)

    def _build_keyboard(self, appointment_id: str) -> InlineKeyboardMarkup:
        """Build inline keyboard with action buttons."""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Подтвердить",
                        callback_data=f"confirm:{appointment_id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Отменить",
                        callback_data=f"cancel:{appointment_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Перенести",
                        callback_data=f"reschedule:{appointment_id}",
                    ),
                ],
            ]
        )

    async def send_notification(
        self,
        recipient_id: str | int,
        message: RenderedMessage,
        appointment_id: str | None = None,
    ) -> DeliveryResult:
        """Send a notification message to a Telegram user."""
        telegram_id = int(recipient_id)

        # Apply rate limiting
        await self._rate_limiter.acquire(telegram_id)

        keyboard = None
        if message.has_buttons and appointment_id:
            keyboard = self._build_keyboard(appointment_id)

        try:
            sent = await self._bot.send_message(
                chat_id=telegram_id,
                text=message.text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            logger.info(
                "telegram_message_sent",
                telegram_id=telegram_id,
                message_id=sent.message_id,
                notification_type=message.notification_type,
            )
            return DeliveryResult(
                channel=Channel.TELEGRAM,
                status=DeliveryStatus.SENT,
                message_id=str(sent.message_id),
            )

        except TelegramRetryAfter as exc:
            logger.warning(
                "telegram_rate_limited",
                telegram_id=telegram_id,
                retry_after=exc.retry_after,
            )
            await asyncio.sleep(exc.retry_after)
            # Retry once after waiting
            sent = await self._bot.send_message(
                chat_id=telegram_id,
                text=message.text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            return DeliveryResult(
                channel=Channel.TELEGRAM,
                status=DeliveryStatus.SENT,
                message_id=str(sent.message_id),
            )

        except TelegramForbiddenError:
            logger.warning(
                "telegram_bot_blocked",
                telegram_id=telegram_id,
            )
            # Signal to caller that channel should be deactivated
            return DeliveryResult(
                channel=Channel.TELEGRAM,
                status=DeliveryStatus.FAILED,
                error="bot_blocked_by_user",
            )

        except Exception as exc:
            logger.error(
                "telegram_send_error",
                telegram_id=telegram_id,
                error=str(exc),
            )
            return DeliveryResult(
                channel=Channel.TELEGRAM,
                status=DeliveryStatus.FAILED,
                error=str(exc),
            )

    async def _handle_callback(self, callback: CallbackQuery) -> None:
        """
        Handle inline button press.
        Responds within 3 seconds (Telegram requirement).
        """
        if not callback.data:
            await callback.answer()
            return

        parts = callback.data.split(":", 1)
        if len(parts) != 2:
            await callback.answer("Неизвестное действие")
            return

        action, appointment_id = parts[0], parts[1]

        # Import here to avoid circular imports
        from app.services.action_handler import handle_client_action

        try:
            result_text = await asyncio.wait_for(
                handle_client_action(
                    action=action,
                    appointment_id=appointment_id,
                    client_channel_id=str(callback.from_user.id),
                    channel=Channel.TELEGRAM,
                ),
                timeout=3.0,
            )
            await callback.answer(result_text, show_alert=False)
        except asyncio.TimeoutError:
            await callback.answer("Обрабатываем запрос...")
        except Exception as exc:
            logger.error("callback_handler_error", error=str(exc))
            await callback.answer("Ошибка. Попробуйте позже.")

    async def _handle_start(self, message: Message) -> None:
        """Handle /start command — prompt for phone number."""
        await message.answer(
            "👋 Привет! Я бот-уведомитель.\n\n"
            "Чтобы получать уведомления о ваших записях, "
            "отправьте ваш номер телефона в формате +79001234567"
        )

    async def _handle_unsubscribe(self, message: Message) -> None:
        """Handle /unsubscribe command."""
        from app.services.action_handler import handle_unsubscribe

        await handle_unsubscribe(
            channel_user_id=str(message.from_user.id),
            channel=Channel.TELEGRAM,
        )
        await message.answer(
            "✅ Вы отписались от уведомлений в Telegram.\n"
            "Для повторной подписки отправьте /start"
        )

    async def start_polling(self) -> None:
        """Start the aiogram polling loop (for development/testing)."""
        logger.info("telegram_polling_started")
        await self._dispatcher.start_polling(self._bot)

    async def set_webhook(self, webhook_url: str) -> None:
        """Set Telegram webhook URL."""
        await self._bot.set_webhook(webhook_url)
        logger.info("telegram_webhook_set", url=webhook_url)

    async def process_update(self, update_data: dict) -> None:
        """Process a single update received via webhook."""
        from aiogram.types import Update

        update = Update.model_validate(update_data)
        await self._dispatcher.feed_update(self._bot, update)

    async def close(self) -> None:
        """Close the bot session."""
        await self._bot.session.close()


# Module-level singleton
_telegram_adapter: TelegramAdapter | None = None


def get_telegram_adapter() -> TelegramAdapter:
    global _telegram_adapter
    if _telegram_adapter is None:
        _telegram_adapter = TelegramAdapter()
    return _telegram_adapter
