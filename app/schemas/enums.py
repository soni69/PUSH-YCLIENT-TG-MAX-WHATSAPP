"""
app/schemas/enums.py — Shared enumerations used across models and schemas.
"""

from __future__ import annotations

from enum import Enum


class NotificationType(str, Enum):
    NEW_APPOINTMENT = "new_appointment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"
    CHANGED = "changed"
    REMINDER_24H = "reminder_24h"
    REMINDER_2H = "reminder_2h"
    BIRTHDAY = "birthday"


class Channel(str, Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    MAX = "max"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


class AppointmentStatus(str, Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    COMPLETED = "completed"


class ReminderType(str, Enum):
    REMINDER_24H = "reminder_24h"
    REMINDER_2H = "reminder_2h"
    BIRTHDAY = "birthday"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ClientAction(str, Enum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    RESCHEDULE = "reschedule"
