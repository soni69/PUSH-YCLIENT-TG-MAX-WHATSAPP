"""
app/services/dispatcher.py — Routes notifications to the correct messenger adapters.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client, ClientChannelSettings
from app.schemas.enums import Channel, DeliveryStatus, NotificationType
from app.schemas.notification import DeliveryResult
from app.services.client_registry import ClientRegistry
from app.services.template_engine import RenderedMessage
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.adapters.base import BaseAdapter

logger = get_logger(__name__)

# Notification types that bypass quiet hours
URGENT_TYPES = {NotificationType.IN_PROGRESS.value}


class Dispatcher:
    """
    Routes a rendered notification to all active channels of a client.

    Logic:
    1. Get all active channel settings for the client
    2. For each channel:
       a. Check channel is enabled
       b. Check notification type is allowed
       c. Check current time is outside quiet hours (unless urgent)
    3. Send via the appropriate adapter
    4. Return list of delivery results
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._registry = ClientRegistry(db)

    async def dispatch(
        self,
        yclients_client_id: str,
        notification_type: str,
        rendered_message: RenderedMessage,
        appointment_id: str | None = None,
    ) -> list[DeliveryResult]:
        """Dispatch a notification to all eligible channels."""
        channel_settings = await self._registry.get_active_channels(yclients_client_id)

        if not channel_settings:
            logger.warning(
                "no_active_channels",
                client_id=yclients_client_id,
                notification_type=notification_type,
            )
            return []

        client = await self._registry.get_client(yclients_client_id)
        if client is None:
            return []

        results: list[DeliveryResult] = []

        for settings in channel_settings:
            if not settings.is_enabled:
                continue

            if not self._is_type_allowed(settings, notification_type):
                logger.info(
                    "notification_type_filtered",
                    client_id=yclients_client_id,
                    channel=settings.channel,
                    notification_type=notification_type,
                )
                continue

            if self._is_quiet_hours(settings) and notification_type not in URGENT_TYPES:
                logger.info(
                    "notification_deferred_quiet_hours",
                    client_id=yclients_client_id,
                    channel=settings.channel,
                )
                # Defer — create a scheduled reminder
                results.append(
                    DeliveryResult(
                        channel=Channel(settings.channel),
                        status=DeliveryStatus.SKIPPED,
                        error="quiet_hours",
                    )
                )
                continue

            adapter = self._get_adapter(settings.channel)
            if adapter is None:
                continue

            recipient_id = self._get_recipient_id(client, settings.channel)
            if recipient_id is None:
                logger.warning(
                    "no_recipient_id",
                    client_id=yclients_client_id,
                    channel=settings.channel,
                )
                continue

            result = await adapter.send_notification(
                recipient_id=recipient_id,
                message=rendered_message,
                appointment_id=appointment_id,
            )
            results.append(result)

            # Deactivate channel if bot was blocked
            if (
                result.status == DeliveryStatus.FAILED
                and result.error == "bot_blocked_by_user"
            ):
                await self._registry.deactivate_channel(
                    yclients_client_id,
                    Channel(settings.channel),
                    reason="bot_blocked_by_user",
                )

            # Deactivate WhatsApp if phone not registered
            if (
                result.status == DeliveryStatus.FAILED
                and result.error == "phone_not_on_whatsapp"
            ):
                await self._registry.deactivate_channel(
                    yclients_client_id,
                    Channel.WHATSAPP,
                    reason="phone_not_on_whatsapp",
                )

        return results

    def _is_type_allowed(
        self, settings: ClientChannelSettings, notification_type: str
    ) -> bool:
        """Check if the notification type is allowed by channel settings."""
        allowed = settings.notification_types
        if not allowed:
            return True
        if "all" in allowed:
            return True
        return notification_type in allowed

    def _is_quiet_hours(self, settings: ClientChannelSettings) -> bool:
        """Check if current time falls within the client's quiet hours."""
        if settings.quiet_hours_start is None or settings.quiet_hours_end is None:
            return False

        try:
            tz = ZoneInfo(settings.timezone or "Europe/Moscow")
        except Exception:
            tz = ZoneInfo("Europe/Moscow")

        now = datetime.now(tz).time()
        start = settings.quiet_hours_start
        end = settings.quiet_hours_end

        # Handle overnight quiet hours (e.g. 22:00 → 09:00)
        if start > end:
            return now >= start or now < end
        return start <= now < end

    def _get_adapter(self, channel: str) -> "BaseAdapter | None":
        """Return the adapter for the given channel."""
        if channel == Channel.TELEGRAM.value:
            from app.adapters.telegram_adapter import get_telegram_adapter
            return get_telegram_adapter()
        elif channel == Channel.WHATSAPP.value:
            from app.adapters.whatsapp_adapter import get_whatsapp_adapter
            return get_whatsapp_adapter()
        elif channel == Channel.MAX.value:
            from app.adapters.max_adapter import get_max_adapter
            return get_max_adapter()
        return None

    def _get_recipient_id(self, client: Client, channel: str) -> str | int | None:
        """Extract the messenger-specific recipient ID from the client record."""
        if channel == Channel.TELEGRAM.value:
            return client.telegram_id
        elif channel == Channel.WHATSAPP.value:
            return client.whatsapp_phone_enc
        elif channel == Channel.MAX.value:
            return client.max_user_id
        return None
