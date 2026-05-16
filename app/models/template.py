"""
app/models/template.py — NotificationTemplate ORM model.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class NotificationTemplate(Base, TimestampMixin):
    """
    Message template for a specific notification type and channel.
    UNIQUE(notification_type, channel, language) ensures one active template per combo.
    """

    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint(
            "notification_type",
            "channel",
            "language",
            name="uq_template_type_channel_lang",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # new_appointment | confirmed | cancelled | in_progress | changed |
    # reminder_24h | reminder_2h | birthday
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # telegram | whatsapp | max
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    # Optional subject line (reserved for future email channel)
    subject: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Jinja2 template body with {{variable}} placeholders
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 'system' for seed data, or admin username for custom templates
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<NotificationTemplate id={self.id} type={self.notification_type!r} "
            f"channel={self.channel!r} lang={self.language!r}>"
        )
