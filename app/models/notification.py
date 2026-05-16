"""
app/models/notification.py — NotificationLog and ScheduledReminder ORM models.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base
from app.models.mixins import TimestampMixin


class NotificationLog(Base):
    """
    Audit log of every notification send attempt.
    Indexed on client_id, appointment_id, sent_at for fast queries.
    """

    __tablename__ = "notification_log"
    __table_args__ = (
        Index("idx_notif_log_client_id", "client_id"),
        Index("idx_notif_log_appointment_id", "appointment_id"),
        Index("idx_notif_log_sent_at", "sent_at"),
        Index("idx_notif_log_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    appointment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # pending | sent | delivered | failed | skipped
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Message ID returned by the messenger API
    message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationLog id={self.id} client={self.client_id!r} "
            f"type={self.notification_type!r} status={self.status!r}>"
        )


class ScheduledReminder(Base, TimestampMixin):
    """
    Tracks scheduled reminders (24h and 2h before appointment, birthdays).
    UNIQUE(appointment_id, reminder_type) prevents duplicate scheduling.
    """

    __tablename__ = "scheduled_reminders"
    __table_args__ = (
        UniqueConstraint(
            "appointment_id", "reminder_type", name="uq_reminder_appointment_type"
        ),
        Index("idx_reminders_scheduled_at", "scheduled_at"),
        Index("idx_reminders_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appointment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # reminder_24h | reminder_2h | birthday
    reminder_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # pending | sent | cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ScheduledReminder id={self.id} appointment={self.appointment_id!r} "
            f"type={self.reminder_type!r} at={self.scheduled_at}>"
        )
