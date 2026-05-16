"""
app/services/action_handler.py — Handles interactive client actions (confirm/cancel/reschedule).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models.task import ActionDedup
from app.schemas.enums import Channel
from app.services.yclients_client import (
    YCLIENTS_STATUS_CANCELLED,
    YCLIENTS_STATUS_CONFIRMED,
    get_yclients_client,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

DEDUP_WINDOW_SECONDS = 30


async def handle_client_action(
    action: str,
    appointment_id: str,
    client_channel_id: str,
    channel: Channel,
) -> str:
    """
    Process a client action (confirm/cancel/reschedule).
    Returns a human-readable result message.
    """
    factory = get_session_factory()
    async with factory() as db:
        # Deduplication check
        if await _is_duplicate_action(db, appointment_id, action, client_channel_id, channel):
            return "Действие уже выполнено"

        # Record the action
        await _record_action(db, appointment_id, action, client_channel_id, channel)
        await db.commit()

    yclients = get_yclients_client()

    if action == "confirm":
        success = await yclients.update_appointment_status(
            appointment_id=int(appointment_id),
            status_id=YCLIENTS_STATUS_CONFIRMED,
        )
        if success:
            logger.info(
                "appointment_confirmed_by_client",
                appointment_id=appointment_id,
                channel=channel.value,
            )
            return "✅ Запись подтверждена!"
        else:
            return "Ошибка подтверждения. Позвоните в салон."

    elif action == "cancel":
        success = await yclients.update_appointment_status(
            appointment_id=int(appointment_id),
            status_id=YCLIENTS_STATUS_CANCELLED,
        )
        if success:
            logger.info(
                "appointment_cancelled_by_client",
                appointment_id=appointment_id,
                channel=channel.value,
            )
            return "❌ Запись отменена."
        else:
            return "Ошибка отмены. Позвоните в салон."

    elif action == "reschedule":
        return "🔄 Для переноса записи позвоните в салон."

    return "Неизвестное действие"


async def _is_duplicate_action(
    db: AsyncSession,
    appointment_id: str,
    action: str,
    client_id: str,
    channel: Channel,
) -> bool:
    """Check if the same action was performed within the dedup window."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(ActionDedup).where(
            ActionDedup.appointment_id == appointment_id,
            ActionDedup.action == action,
            ActionDedup.client_id == client_id,
            ActionDedup.channel == channel.value,
            ActionDedup.expires_at > now,
        )
    )
    return result.scalar_one_or_none() is not None


async def _record_action(
    db: AsyncSession,
    appointment_id: str,
    action: str,
    client_id: str,
    channel: Channel,
) -> None:
    """Record an action in the dedup table."""
    now = datetime.now(timezone.utc)
    dedup = ActionDedup(
        appointment_id=appointment_id,
        action=action,
        client_id=client_id,
        channel=channel.value,
        executed_at=now,
        expires_at=now + timedelta(seconds=DEDUP_WINDOW_SECONDS),
    )
    db.add(dedup)
    await db.flush()


async def handle_unsubscribe(channel_user_id: str, channel: Channel) -> None:
    """Unsubscribe a user from a channel."""
    factory = get_session_factory()
    async with factory() as db:
        from app.services.client_registry import ClientRegistry
        from sqlalchemy import select
        from app.models.client import Client

        # Find client by channel ID
        if channel == Channel.TELEGRAM:
            result = await db.execute(
                select(Client).where(
                    Client.telegram_id == int(channel_user_id)
                )
            )
        elif channel == Channel.MAX:
            result = await db.execute(
                select(Client).where(Client.max_user_id == channel_user_id)
            )
        else:
            return

        client = result.scalar_one_or_none()
        if client is None:
            return

        registry = ClientRegistry(db)
        await registry.unsubscribe(client.yclients_client_id, channel)
        await db.commit()
        logger.info(
            "client_unsubscribed",
            channel=channel.value,
            channel_user_id=channel_user_id,
        )


async def handle_max_phone_link(phone: str, max_user_id: str) -> None:
    """Link a MAX user to a client by phone number."""
    factory = get_session_factory()
    async with factory() as db:
        from app.services.client_registry import ClientRegistry
        registry = ClientRegistry(db)
        client = await registry.link_max(phone=phone, max_user_id=max_user_id)
        await db.commit()
        if client:
            logger.info(
                "max_phone_linked",
                max_user_id=max_user_id,
                yclients_client_id=client.yclients_client_id,
            )
