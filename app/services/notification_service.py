"""
app/services/notification_service.py — Central notification orchestration service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationLog
from app.schemas.enums import Channel, DeliveryStatus, NotificationType
from app.schemas.notification import DeliveryResult
from app.schemas.yclients import AppointmentData, ClientInfo
from app.services.client_registry import ClientRegistry
from app.services.dispatcher import Dispatcher
from app.services.template_engine import TemplateEngine
from app.services.yclients_client import get_yclients_client
from app.utils.logging import get_logger

logger = get_logger(__name__)

# YClients status ID → NotificationType mapping
YCLIENTS_STATUS_MAP = {
    1: NotificationType.CONFIRMED,
    2: NotificationType.CANCELLED,
    3: NotificationType.IN_PROGRESS,
    7: NotificationType.CONFIRMED,  # completed → treat as confirmed
}


class NotificationService:
    """
    Orchestrates the full notification pipeline:
    event → dedup check → template render → dispatch → log
    """

    def __init__(self, db: AsyncSession, redis=None) -> None:
        self._db = db
        self._redis = redis
        self._registry = ClientRegistry(db)
        self._template_engine = TemplateEngine(db, redis)
        self._dispatcher = Dispatcher(db)

    async def process_yclients_event(self, event_data: dict[str, Any]) -> None:
        """
        Process a raw YClients event (from webhook or polling).
        Determines notification type and triggers delivery.
        """
        resource = event_data.get("resource", "")
        status = event_data.get("status", "")
        resource_id = event_data.get("resource_id")

        if resource != "record":
            return

        yclients = get_yclients_client()
        appointment = await yclients.get_appointment(int(resource_id))
        if appointment is None:
            logger.warning("appointment_not_found", resource_id=resource_id)
            return

        if appointment.client_id is None:
            return

        client_info = await yclients.get_client(appointment.client_id)
        if client_info is None:
            return

        # Determine notification type
        if status == "create":
            notification_type = NotificationType.NEW_APPOINTMENT
        elif status == "update":
            notification_type = YCLIENTS_STATUS_MAP.get(
                appointment.status_id, NotificationType.CHANGED
            )
        else:
            return

        await self.send_appointment_notification(
            appointment=appointment,
            client_info=client_info,
            notification_type=notification_type,
        )

    async def send_appointment_notification(
        self,
        appointment: AppointmentData,
        client_info: ClientInfo,
        notification_type: NotificationType,
    ) -> list[DeliveryResult]:
        """Send a notification for a specific appointment event."""
        client_id = str(client_info.id)
        appointment_id = str(appointment.id)

        # Deduplication check
        if await self._check_dedup(client_id, appointment_id, notification_type.value):
            logger.info(
                "notification_deduplicated",
                client_id=client_id,
                appointment_id=appointment_id,
                notification_type=notification_type.value,
            )
            return []

        # Build template context
        context = self._build_context(appointment, client_info)

        # Get active channels to determine which adapters to use
        channel_settings = await self._registry.get_active_channels(client_id)
        if not channel_settings:
            logger.warning("no_active_channels", client_id=client_id)
            return []

        all_results: list[DeliveryResult] = []

        for settings in channel_settings:
            if not settings.is_enabled:
                continue

            rendered = await self._template_engine.render(
                notification_type=notification_type.value,
                channel=settings.channel,
                context=context,
            )
            if rendered is None:
                continue

            results = await self._dispatcher.dispatch(
                yclients_client_id=client_id,
                notification_type=notification_type.value,
                rendered_message=rendered,
                appointment_id=appointment_id,
            )
            all_results.extend(results)

        # Log all results
        for result in all_results:
            await self._log_notification(
                client_id=client_id,
                channel=result.channel.value,
                notification_type=notification_type.value,
                appointment_id=appointment_id,
                result=result,
            )

        return all_results

    async def send_reminder(
        self,
        appointment_id: str,
        client_id: str,
        reminder_type: str,
    ) -> list[DeliveryResult]:
        """Send a reminder notification (24h or 2h before appointment)."""
        yclients = get_yclients_client()
        appointment = await yclients.get_appointment(int(appointment_id))
        if appointment is None:
            return []

        client_info = await yclients.get_client(int(client_id))
        if client_info is None:
            return []

        notification_type = NotificationType(reminder_type)
        return await self.send_appointment_notification(
            appointment=appointment,
            client_info=client_info,
            notification_type=notification_type,
        )

    async def send_birthday_greeting(self, client_id: str) -> list[DeliveryResult]:
        """Send a birthday greeting to a client."""
        yclients = get_yclients_client()
        client_info = await yclients.get_client(int(client_id))
        if client_info is None:
            return []

        context = {
            "client_name": client_info.name,
            "salon_name": "",
            "salon_phone": "",
            "salon_address": "",
            "master_name": "",
            "service_name": "",
            "appointment_date": "",
            "appointment_time": "",
        }

        channel_settings = await self._registry.get_active_channels(client_id)
        all_results: list[DeliveryResult] = []

        for settings in channel_settings:
            if not settings.is_enabled:
                continue
            rendered = await self._template_engine.render(
                notification_type=NotificationType.BIRTHDAY.value,
                channel=settings.channel,
                context=context,
            )
            if rendered is None:
                continue

            results = await self._dispatcher.dispatch(
                yclients_client_id=client_id,
                notification_type=NotificationType.BIRTHDAY.value,
                rendered_message=rendered,
            )
            all_results.extend(results)

        return all_results

    async def _check_dedup(
        self,
        client_id: str,
        appointment_id: str,
        notification_type: str,
        window_minutes: int = 10,
    ) -> bool:
        """
        Return True if an identical notification was sent within window_minutes.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        result = await self._db.execute(
            select(NotificationLog).where(
                NotificationLog.client_id == client_id,
                NotificationLog.appointment_id == appointment_id,
                NotificationLog.notification_type == notification_type,
                NotificationLog.status.in_(
                    [DeliveryStatus.SENT.value, DeliveryStatus.DELIVERED.value]
                ),
                NotificationLog.created_at >= cutoff,
            )
        )
        return result.scalar_one_or_none() is not None

    async def _log_notification(
        self,
        client_id: str,
        channel: str,
        notification_type: str,
        appointment_id: str | None,
        result: DeliveryResult,
    ) -> None:
        """Insert a record into notification_log."""
        log_entry = NotificationLog(
            client_id=client_id,
            channel=channel,
            notification_type=notification_type,
            appointment_id=appointment_id,
            status=result.status.value,
            error_message=result.error,
            message_id=result.message_id,
            sent_at=datetime.now(timezone.utc) if result.status == DeliveryStatus.SENT else None,
        )
        self._db.add(log_entry)
        await self._db.flush()

    def _build_context(
        self, appointment: AppointmentData, client_info: ClientInfo
    ) -> dict[str, Any]:
        """Build the Jinja2 template context from appointment and client data."""
        appt_dt = appointment.appointment_datetime
        service_name = ""
        if appointment.services:
            service_name = appointment.services[0].title

        master_name = ""
        if appointment.staff:
            master_name = appointment.staff.name

        return {
            "client_name": client_info.name,
            "master_name": master_name,
            "service_name": service_name,
            "appointment_date": appt_dt.strftime("%d.%m.%Y") if appt_dt else "",
            "appointment_time": appt_dt.strftime("%H:%M") if appt_dt else "",
            "salon_address": "",   # Populated from company settings if available
            "salon_phone": "",
            "salon_name": "",
        }


async def update_delivery_status(
    message_id: str,
    channel: Channel,
    status: DeliveryStatus,
) -> None:
    """
    Update notification_log delivery status.
    Called from adapter webhook handlers.
    """
    from app.database import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        await db.execute(
            update(NotificationLog)
            .where(
                NotificationLog.message_id == message_id,
                NotificationLog.channel == channel.value,
            )
            .values(
                status=status.value,
                delivered_at=datetime.now(timezone.utc)
                if status == DeliveryStatus.DELIVERED
                else None,
            )
        )
        await db.commit()
