"""
app/tasks/scheduler_tasks.py — Periodic Celery tasks: polling, reminders, birthdays.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.tasks.celery_app import celery_app
from app.utils.logging import get_logger

logger = get_logger(__name__)

MAX_QUEUE_SIZE = 1000


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_queue_size() -> int:
    """Get approximate number of pending tasks in the notifications queue."""
    try:
        from app.tasks.celery_app import celery_app as app
        inspect = app.control.inspect()
        reserved = inspect.reserved() or {}
        total = sum(len(tasks) for tasks in reserved.values())
        return total
    except Exception:
        return 0


@celery_app.task(name="app.tasks.scheduler_tasks.poll_yclients")
def poll_yclients() -> dict[str, Any]:
    """
    Poll YClients API for new/changed appointments in the last polling window.
    Skips if the task queue is overloaded (> 1000 pending tasks).
    """
    queue_size = _get_queue_size()
    if queue_size > MAX_QUEUE_SIZE:
        logger.warning("queue_overloaded_skipping_poll", queue_size=queue_size)
        return {"status": "skipped", "reason": "queue_overloaded"}

    return _run_async(_poll_yclients_async())


async def _poll_yclients_async() -> dict[str, Any]:
    from app.config import get_settings
    from app.services.yclients_client import get_yclients_client, CircuitBreakerOpen

    settings = get_settings()
    yclients = get_yclients_client()

    now = datetime.now(timezone.utc)
    window = timedelta(seconds=settings.polling_interval_seconds + 30)  # slight overlap
    start = now - window

    try:
        appointments = await yclients.get_appointments(
            start_date=start,
            end_date=now,
        )
    except CircuitBreakerOpen:
        logger.warning("poll_skipped_circuit_breaker_open")
        return {"status": "skipped", "reason": "circuit_breaker_open"}

    processed = 0
    for appointment in appointments:
        if appointment.client_id is None:
            continue

        from app.tasks.notification_tasks import send_notification_task
        from app.schemas.enums import NotificationType

        # Determine notification type based on status
        from app.services.notification_service import YCLIENTS_STATUS_MAP
        notification_type = YCLIENTS_STATUS_MAP.get(
            appointment.status_id, NotificationType.CHANGED
        )

        # Get client info
        client_info = await yclients.get_client(appointment.client_id)
        if client_info is None:
            continue

        payload = {
            "notification_type": notification_type.value,
            "appointment": appointment.model_dump(),
            "client": client_info.model_dump(),
        }

        send_notification_task.apply_async(
            args=[payload],
            queue="notifications",
        )
        processed += 1

    logger.info("poll_completed", appointments_found=len(appointments), processed=processed)
    return {"status": "ok", "processed": processed}


@celery_app.task(name="app.tasks.scheduler_tasks.check_reminders")
def check_reminders() -> dict[str, Any]:
    """Check for appointments that need 24h or 2h reminders."""
    return _run_async(_check_reminders_async())


async def _check_reminders_async() -> dict[str, Any]:
    from app.database import get_session_factory
    from app.models.notification import ScheduledReminder
    from sqlalchemy import select, update

    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(minutes=5)

    async with factory() as db:
        result = await db.execute(
            select(ScheduledReminder).where(
                ScheduledReminder.status == "pending",
                ScheduledReminder.scheduled_at <= window_end,
                ScheduledReminder.scheduled_at >= now - timedelta(minutes=5),
            )
        )
        reminders = list(result.scalars().all())

        sent = 0
        for reminder in reminders:
            from app.tasks.notification_tasks import send_reminder_task

            task = send_reminder_task.apply_async(
                kwargs={
                    "appointment_id": reminder.appointment_id,
                    "client_id": reminder.client_id,
                    "reminder_type": reminder.reminder_type,
                },
                queue="notifications",
            )

            await db.execute(
                update(ScheduledReminder)
                .where(ScheduledReminder.id == reminder.id)
                .values(status="sent", celery_task_id=task.id)
            )
            sent += 1

        await db.commit()

    logger.info("reminders_dispatched", count=sent)
    return {"status": "ok", "sent": sent}


@celery_app.task(name="app.tasks.scheduler_tasks.send_birthday_greetings")
def send_birthday_greetings() -> dict[str, Any]:
    """Send birthday greetings to clients whose birthday is today."""
    return _run_async(_send_birthday_greetings_async())


async def _send_birthday_greetings_async() -> dict[str, Any]:
    from app.services.yclients_client import get_yclients_client

    yclients = get_yclients_client()
    today = date.today()

    clients = await yclients.get_clients_with_birthdays(today)
    sent = 0

    for client_info in clients:
        from app.database import get_session_factory
        from app.services.notification_service import NotificationService

        factory = get_session_factory()
        async with factory() as db:
            service = NotificationService(db)
            await service.send_birthday_greeting(str(client_info.id))
            await db.commit()
        sent += 1

    logger.info("birthday_greetings_sent", count=sent)
    return {"status": "ok", "sent": sent}


@celery_app.task(name="app.tasks.scheduler_tasks.schedule_appointment_reminders")
def schedule_appointment_reminders(
    appointment_id: str,
    client_id: str,
    appointment_datetime_iso: str,
) -> dict[str, Any]:
    """
    Schedule 24h and 2h reminders for a new appointment.
    Called when a new_appointment notification is processed.
    """
    return _run_async(
        _schedule_reminders_async(appointment_id, client_id, appointment_datetime_iso)
    )


async def _schedule_reminders_async(
    appointment_id: str,
    client_id: str,
    appointment_datetime_iso: str,
) -> dict[str, Any]:
    from app.database import get_session_factory
    from app.models.notification import ScheduledReminder
    from sqlalchemy.dialects.postgresql import insert

    appt_dt = datetime.fromisoformat(appointment_datetime_iso)
    if appt_dt.tzinfo is None:
        appt_dt = appt_dt.replace(tzinfo=timezone.utc)

    reminders = [
        ("reminder_24h", appt_dt - timedelta(hours=24)),
        ("reminder_2h", appt_dt - timedelta(hours=2)),
    ]

    factory = get_session_factory()
    async with factory() as db:
        for reminder_type, scheduled_at in reminders:
            if scheduled_at <= datetime.now(timezone.utc):
                continue  # Skip past reminders

            # Use INSERT ... ON CONFLICT DO NOTHING for idempotency
            stmt = insert(ScheduledReminder).values(
                appointment_id=appointment_id,
                client_id=client_id,
                reminder_type=reminder_type,
                scheduled_at=scheduled_at,
                status="pending",
            ).on_conflict_do_nothing(
                index_elements=["appointment_id", "reminder_type"]
            )
            await db.execute(stmt)

        await db.commit()

    return {"status": "ok", "appointment_id": appointment_id}
