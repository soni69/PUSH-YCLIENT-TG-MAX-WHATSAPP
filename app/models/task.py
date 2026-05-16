"""
app/models/task.py — TaskQueue and ActionDedup ORM models.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base
from app.models.mixins import TimestampMixin


class TaskQueue(Base, TimestampMixin):
    """
    Persistent task state for Celery jobs.
    Used to ensure idempotency — a task with the same task_id is never
    executed twice.
    """

    __tablename__ = "task_queue"
    __table_args__ = (
        Index("idx_task_queue_status", "status"),
        Index("idx_task_queue_next_retry", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Celery task UUID — unique per task instance
    task_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # pending | running | success | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TaskQueue id={self.id} task_id={self.task_id!r} "
            f"type={self.task_type!r} status={self.status!r}>"
        )


class ActionDedup(Base):
    """
    Deduplication table for interactive client actions (confirm/cancel/reschedule).
    Prevents double-processing when a button is pressed multiple times within 30 seconds.
    """

    __tablename__ = "action_dedup"
    __table_args__ = (
        Index(
            "idx_dedup_appointment_action",
            "appointment_id",
            "action",
            "expires_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appointment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # confirm | cancel | reschedule
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # executed_at + 30 seconds
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ActionDedup id={self.id} appointment={self.appointment_id!r} "
            f"action={self.action!r} expires={self.expires_at}>"
        )
