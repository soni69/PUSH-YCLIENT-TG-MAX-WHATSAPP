"""
app/tasks/cleanup_tasks.py — Periodic cleanup of old notification logs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.tasks.celery_app import celery_app
from app.utils.logging import get_logger

logger = get_logger(__name__)

LOG_RETENTION_DAYS = 90


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.tasks.cleanup_tasks.cleanup_old_logs")
def cleanup_old_logs() -> dict[str, Any]:
    """Delete notification_log entries older than 90 days."""
    return _run_async(_cleanup_old_logs_async())


async def _cleanup_old_logs_async() -> dict[str, Any]:
    from app.database import get_session_factory
    from app.models.notification import NotificationLog
    from sqlalchemy import delete

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            delete(NotificationLog).where(NotificationLog.created_at < cutoff)
        )
        deleted = result.rowcount
        await db.commit()

    logger.info("old_logs_cleaned", deleted=deleted, cutoff=cutoff.isoformat())
    return {"status": "ok", "deleted": deleted}


@celery_app.task(name="app.tasks.cleanup_tasks.cleanup_expired_dedup")
def cleanup_expired_dedup() -> dict[str, Any]:
    """Delete expired action_dedup entries."""
    return _run_async(_cleanup_expired_dedup_async())


async def _cleanup_expired_dedup_async() -> dict[str, Any]:
    from app.database import get_session_factory
    from app.models.task import ActionDedup
    from sqlalchemy import delete

    now = datetime.now(timezone.utc)

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            delete(ActionDedup).where(ActionDedup.expires_at < now)
        )
        deleted = result.rowcount
        await db.commit()

    return {"status": "ok", "deleted": deleted}
