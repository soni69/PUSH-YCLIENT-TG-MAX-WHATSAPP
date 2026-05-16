"""
app/tasks/celery_app.py — Celery application configuration.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "yclients_bot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.notification_tasks",
        "app.tasks.scheduler_tasks",
        "app.tasks.cleanup_tasks",
    ],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone=settings.timezone,
    enable_utc=True,
    # Task behaviour
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    # Result backend
    result_expires=3600,
    # Worker
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    # Queues
    task_default_queue="default",
    task_queues={
        "notifications": {"exchange": "notifications", "routing_key": "notifications"},
        "default": {"exchange": "default", "routing_key": "default"},
    },
    task_routes={
        "app.tasks.notification_tasks.*": {"queue": "notifications"},
        "app.tasks.scheduler_tasks.*": {"queue": "default"},
        "app.tasks.cleanup_tasks.*": {"queue": "default"},
    },
    # Beat schedule
    beat_schedule={
        "poll-yclients": {
            "task": "app.tasks.scheduler_tasks.poll_yclients",
            "schedule": settings.polling_interval_seconds,
        },
        "check-reminders": {
            "task": "app.tasks.scheduler_tasks.check_reminders",
            "schedule": 60.0,
        },
        "send-birthday-greetings": {
            "task": "app.tasks.scheduler_tasks.send_birthday_greetings",
            "schedule": crontab(hour=9, minute=50),
        },
        "cleanup-old-logs": {
            "task": "app.tasks.cleanup_tasks.cleanup_old_logs",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
