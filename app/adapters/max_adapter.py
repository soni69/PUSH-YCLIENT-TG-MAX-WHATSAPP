"""
app/adapters/max_adapter.py — MAX Bot API adapter (botapi.max.ru).
"""

from __future__ import annotations

import asyncio
import time as time_module
from typing import Any

import httpx

from app.adapters.base import BaseAdapter
from app.config import get_settings
from app.schemas.enums import Channel, DeliveryStatus
from app.schemas.notification import DeliveryResult
from app.services.template_engine import RenderedMessage
from app.utils.logging import get_logger

logger = get_logger(__name__)

MAX_API_BASE = "https://botapi.max.ru"


class MaxAdapter(BaseAdapter):
    """
    Sends notifications via MAX Bot API.

    Features:
    - Inline keyboard with callback buttons
    - Long-polling for incoming updates
    - Reconnect on API unavailability (> 60s → retry after 30s)
    - Markdown-style text formatting
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.max_bot_token
        self._client: httpx.AsyncClient | None = None
        self._polling_marker: int | None = None
        self._polling_task: asyncio.Task | None = None
        self._unavailable_since: float | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=MAX_API_BASE,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(35.0),
            )
        return self._client

    async def close(self) -> None:
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _build_keyboard(self, appointment_id: str) -> dict[str, Any]:
        """Build MAX Bot API inline keyboard payload."""
        return {
            "buttons": [
                [
                    {
                        "type": "callback",
                        "text": "✅ Подтвердить",
                        "payload": f"confirm:{appointment_id}",
                    },
                    {
                        "type": "callback",
                        "text": "❌ Отменить",
                        "payload": f"cancel:{appointment_id}",
                    },
                ],
                [
                    {
                        "type": "callback",
                        "text": "🔄 Перенести",
                        "payload": f"reschedule:{appointment_id}",
                    },
                ],
            ]
        }

    async def send_notification(
        self,
        recipient_id: str | int,
        message: RenderedMessage,
        appointment_id: str | None = None,
    ) -> DeliveryResult:
        """Send a message with optional inline keyboard to a MAX user."""
        max_user_id = str(recipient_id)
        client = await self._get_client()

        payload: dict[str, Any] = {"text": message.text}

        if message.has_buttons and appointment_id:
            payload["attachments"] = [
                {
                    "type": "inline_keyboard",
                    "payload": self._build_keyboard(appointment_id),
                }
            ]

        try:
            response = await client.post(
                "/messages",
                params={"user_id": max_user_id},
                json=payload,
            )
            self._unavailable_since = None  # Reset unavailability timer

            if response.status_code in (200, 201):
                data = response.json()
                message_id = str(data.get("message", {}).get("mid", ""))
                logger.info(
                    "max_message_sent",
                    max_user_id=max_user_id,
                    message_id=message_id,
                    notification_type=message.notification_type,
                )
                return DeliveryResult(
                    channel=Channel.MAX,
                    status=DeliveryStatus.SENT,
                    message_id=message_id,
                )

            logger.error(
                "max_send_error",
                max_user_id=max_user_id,
                status_code=response.status_code,
                response=response.text[:200],
            )
            return DeliveryResult(
                channel=Channel.MAX,
                status=DeliveryStatus.FAILED,
                error=f"HTTP {response.status_code}: {response.text[:100]}",
            )

        except httpx.RequestError as exc:
            now = time_module.monotonic()
            if self._unavailable_since is None:
                self._unavailable_since = now
            elif now - self._unavailable_since > 60:
                logger.error(
                    "max_api_unavailable",
                    duration_seconds=round(now - self._unavailable_since),
                )
            logger.error("max_request_error", error=str(exc))
            return DeliveryResult(
                channel=Channel.MAX,
                status=DeliveryStatus.FAILED,
                error=str(exc),
            )

    async def start_polling(self) -> None:
        """Start long-polling loop in a background task."""
        if self._polling_task and not self._polling_task.done():
            return
        self._polling_task = asyncio.create_task(self._polling_loop())
        logger.info("max_polling_started")

    async def _polling_loop(self) -> None:
        """Long-polling loop: GET /updates?timeout=30&marker={marker}"""
        while True:
            try:
                await self._poll_once()
                self._unavailable_since = None
            except asyncio.CancelledError:
                logger.info("max_polling_stopped")
                break
            except Exception as exc:
                now = time_module.monotonic()
                if self._unavailable_since is None:
                    self._unavailable_since = now

                if now - (self._unavailable_since or now) > 60:
                    logger.error(
                        "max_api_unavailable_polling",
                        error=str(exc),
                    )

                logger.warning("max_polling_error", error=str(exc))
                await asyncio.sleep(30)

    async def _poll_once(self) -> None:
        """Execute one long-poll request and process updates."""
        client = await self._get_client()
        params: dict[str, Any] = {"timeout": 30}
        if self._polling_marker is not None:
            params["marker"] = self._polling_marker

        response = await client.get("/updates", params=params)

        if response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"MAX API returned {response.status_code}",
                request=response.request,
                response=response,
            )

        data = response.json()
        updates = data.get("updates", [])

        for update in updates:
            try:
                await self._process_update(update)
            except Exception as exc:
                logger.error("max_update_process_error", error=str(exc))

        # Advance marker
        new_marker = data.get("marker")
        if new_marker is not None:
            self._polling_marker = new_marker

    async def _process_update(self, update: dict[str, Any]) -> None:
        """Route an incoming MAX update to the appropriate handler."""
        update_type = update.get("update_type")

        if update_type == "bot_started":
            await self._handle_bot_started(update)
        elif update_type == "message_created":
            await self._handle_message(update)
        elif update_type == "message_callback":
            await self._handle_callback(update)

    async def _handle_bot_started(self, update: dict[str, Any]) -> None:
        """Handle bot_started event — save max_user_id."""
        user = update.get("user", {})
        max_user_id = str(user.get("user_id", ""))
        if not max_user_id:
            return

        logger.info("max_bot_started", max_user_id=max_user_id)
        # Send welcome message
        client = await self._get_client()
        await client.post(
            "/messages",
            params={"user_id": max_user_id},
            json={
                "text": (
                    "👋 Привет! Я бот-уведомитель.\n\n"
                    "Отправьте ваш номер телефона в формате +79001234567 "
                    "для получения уведомлений о записях."
                )
            },
        )

    async def _handle_message(self, update: dict[str, Any]) -> None:
        """Handle incoming text message."""
        message = update.get("message", {})
        user = message.get("sender", {})
        max_user_id = str(user.get("user_id", ""))
        text = message.get("body", {}).get("text", "").strip()

        if not max_user_id:
            return

        if text.startswith("/unsubscribe"):
            from app.services.action_handler import handle_unsubscribe
            await handle_unsubscribe(
                channel_user_id=max_user_id,
                channel=Channel.MAX,
            )
            client = await self._get_client()
            await client.post(
                "/messages",
                params={"user_id": max_user_id},
                json={"text": "✅ Вы отписались от уведомлений в MAX."},
            )
        elif text.startswith("+") or text.isdigit():
            # Phone number — attempt to link
            from app.services.action_handler import handle_max_phone_link
            await handle_max_phone_link(phone=text, max_user_id=max_user_id)
        else:
            client = await self._get_client()
            await client.post(
                "/messages",
                params={"user_id": max_user_id},
                json={
                    "text": (
                        "Доступные команды:\n"
                        "/unsubscribe — отписаться от уведомлений\n\n"
                        "Для изменения записи позвоните в салон."
                    )
                },
            )

    async def _handle_callback(self, update: dict[str, Any]) -> None:
        """Handle button callback."""
        callback = update.get("callback", {})
        payload = callback.get("payload", "")
        user = callback.get("user", {})
        max_user_id = str(user.get("user_id", ""))

        parts = payload.split(":", 1)
        if len(parts) != 2:
            return

        action, appointment_id = parts
        from app.services.action_handler import handle_client_action

        try:
            await asyncio.wait_for(
                handle_client_action(
                    action=action,
                    appointment_id=appointment_id,
                    client_channel_id=max_user_id,
                    channel=Channel.MAX,
                ),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("max_callback_timeout", max_user_id=max_user_id)
        except Exception as exc:
            logger.error("max_callback_error", error=str(exc))


# Module-level singleton
_max_adapter: MaxAdapter | None = None


def get_max_adapter() -> MaxAdapter:
    global _max_adapter
    if _max_adapter is None:
        _max_adapter = MaxAdapter()
    return _max_adapter
