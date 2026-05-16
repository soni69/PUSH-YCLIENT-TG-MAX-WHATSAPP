"""
app/tasks/notification_tasks.py — Celery tasks for sending notifications.
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import select, update

from app.tasks.celery_app import celery_app
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Retry delays in seconds: 1 min, 5 min, 15 min, 60 min
RETRY_DELAYS = [60, 300, 900, 3600]


def _run_async(coro):
    """Run an async coroutine in a new event loop (for Celery sync context)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="app.tasks.notification_tasks.send_notification_task",
    max_retries=4,
    queue="notifications",
)
def send_notification_task(self: Task, task_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Send a notification with retry logic.

    Retry delays: 1 min → 5 min → 15 min → 60 min
    Idempotency: checks task_id in task_queue before executing.
    """
    task_id = self.request.id
    return _run_async(_send_notification_async(self, task_id, task_payload))


async def _send_notification_async(
    task: Task,
    task_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.database import get_session_factory
    from app.models.task import TaskQueue
    from app.schemas.enums import TaskStatus

    factory = get_session_factory()

    async with factory() as db:
        # Idempotency check
        result = await db.execute(
            select(TaskQueue).where(TaskQueue.task_id == task_id)
        )
        existing = result.scalar_one_or_none()

        if existing and existing.status == TaskStatus.SUCCESS.value:
            logger.info("task_already_completed", task_id=task_id)
            return {"status": "already_completed"}

        # Create or update task record
        if existing is None:
            task_record = TaskQueue(
                task_id=task_id,
                task_type="send_notification",
                payload=payload,
                status=TaskStatus.RUNNING.value,
                attempts=1,
            )
            db.add(task_record)
        else:
            await db.execute(
                update(TaskQueue)
                .where(TaskQueue.task_id == task_id)
                .values(
                    status=TaskStatus.RUNNING.value,
                    attempts=TaskQueue.attempts + 1,
                )
            )
        await db.commit()

    try:
        # Execute the notification
        result = await _execute_notification(payload)

        # Mark as success
        async with factory() as db:
            await db.execute(
                update(TaskQueue)
                .where(TaskQueue.task_id == task_id)
                .values(status=TaskStatus.SUCCESS.value)
            )
            await db.commit()

        return result

    except Exception as exc:
        attempt = task.request.retries
        logger.error(
            "notification_task_failed",
            task_id=task_id,
            attempt=attempt + 1,
            error=str(exc),
        )

        # Update task record with error
        async with factory() as db:
            delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
            from datetime import datetime, timedelta, timezone
            next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)
            await db.execute(
                update(TaskQueue)
                .where(TaskQueue.task_id == task_id)
                .values(
                    status=TaskStatus.PENDING.value,
                    error_message=str(exc),
                    next_retry_at=next_retry,
                )
            )
            await db.commit()

        if attempt < 4:
            delay = RETRY_DELAYS[attempt]
            raise task.retry(exc=exc, countdown=delay)

        # All retries exhausted — mark as failed
        async with factory() as db:
            await db.execute(
                update(TaskQueue)
                .where(TaskQueue.task_id == task_id)
                .values(status=TaskStatus.FAILED.value)
            )
            await db.commit()

        logger.error(
            "notification_task_permanently_failed",
            task_id=task_id,
            payload=payload,
        )
        return {"status": "failed", "error": str(exc)}


async def _execute_notification(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute the actual notification send."""
    from app.database import get_session_factory
    from app.services.notification_service import NotificationService
    from app.schemas.yclients import AppointmentData, ClientInfo
    from app.schemas.enums import NotificationType

    notification_type = payload.get("notification_type")
    appointment_data = payload.get("appointment")
    client_data = payload.get("client")

    if not all([notification_type, appointment_data, client_data]):
        raise ValueError(f"Invalid payload: {payload}")

    appointment = AppointmentData(**appointment_data)
    client_info = ClientInfo(**client_data)

    factory = get_session_factory()
    async with factory() as db:
        service = NotificationService(db)
        results = await service.send_appointment_notification(
            appointment=appointment,
            client_info=client_info,
            notification_type=NotificationType(notification_type),
        )
        await db.commit()

    return {
        "status": "success",
        "results": [r.model_dump() for r in results],
    }


@celery_app.task(
    name="app.tasks.notification_tasks.send_reminder_task",
    queue="notifications",
)
def send_reminder_task(
    appointment_id: str,
    client_id: str,
    reminder_type: str,
) -> dict[str, Any]:
    """Send a scheduled reminder."""
    return _run_async(_send_reminder_async(appointment_id, client_id, reminder_type))


async def _send_reminder_async(
    appointment_id: str,
    client_id: str,
    reminder_type: str,
) -> dict[str, Any]:
    from app.database import get_session_factory
    from app.services.notification_service import NotificationService

    factory = get_session_factory()
    async with factory() as db:
        service = NotificationService(db)
        results = await service.send_reminder(
            appointment_id=appointment_id,
            client_id=client_id,
            reminder_type=reminder_type,
        )
        await db.commit()

    return {"status": "success", "results": [r.model_dump() for r in results]}


@celery_app.task(
    name="app.tasks.notification_tasks.process_yclients_event_task",
    queue="notifications",
)
def process_yclients_event_task(event_data: dict[str, Any]) -> dict[str, Any]:
    """Process a YClients webhook event."""
    return _run_async(_process_yclients_event_async(event_data))


async def _process_yclients_event_async(event_data: dict[str, Any]) -> dict[str, Any]:
    from app.database import get_session_factory
    from app.services.notification_service import NotificationService

    factory = get_session_factory()
    async with factory() as db:
        service = NotificationService(db)
        await service.process_yclients_event(event_data)
        await db.commit()

    return {"status": "ok"}
