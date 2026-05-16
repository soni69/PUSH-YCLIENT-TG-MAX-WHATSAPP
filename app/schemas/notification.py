"""
app/schemas/notification.py — Pydantic schemas for NotificationLog and ScheduledReminder.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.enums import Channel, DeliveryStatus, NotificationType, ReminderType


class NotificationLogRead(BaseModel):
    id: int
    client_id: str
    channel: Channel
    notification_type: NotificationType
    appointment_id: str | None = None
    status: DeliveryStatus
    error_message: str | None = None
    message_id: str | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationLogFilter(BaseModel):
    client_id: str | None = None
    channel: Channel | None = None
    notification_type: NotificationType | None = None
    status: DeliveryStatus | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class ScheduledReminderRead(BaseModel):
    id: int
    appointment_id: str
    client_id: str
    reminder_type: ReminderType
    scheduled_at: datetime
    status: str
    celery_task_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SendNotificationRequest(BaseModel):
    """Request to manually send a test notification."""
    client_id: str
    notification_type: NotificationType
    channel: Channel | None = None  # None = all active channels
    appointment_id: str | None = None


class DeliveryResult(BaseModel):
    channel: Channel
    status: DeliveryStatus
    message_id: str | None = None
    error: str | None = None
