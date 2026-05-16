"""
app/models/__init__.py — Import all models so Alembic autogenerate detects them.
"""

from app.models.client import Client, ClientChannelSettings  # noqa: F401
from app.models.notification import NotificationLog, ScheduledReminder  # noqa: F401
from app.models.task import ActionDedup, TaskQueue  # noqa: F401
from app.models.template import NotificationTemplate  # noqa: F401

__all__ = [
    "Client",
    "ClientChannelSettings",
    "NotificationLog",
    "ScheduledReminder",
    "NotificationTemplate",
    "TaskQueue",
    "ActionDedup",
]
