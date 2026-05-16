"""
app/models/client.py — Client and ClientChannelSettings ORM models.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.mixins import TimestampMixin


class Client(Base, TimestampMixin):
    """
    Maps a YClients client_id to messenger identifiers.
    One client can be linked to multiple channels simultaneously.
    """

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    yclients_client_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    # SHA-256 hash of the phone number — used for lookup
    whatsapp_phone_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    # Encrypted/masked phone number — used for sending messages
    whatsapp_phone_enc: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    max_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preferred_channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default="telegram"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    channel_settings: Mapped[list[ClientChannelSettings]] = relationship(
        "ClientChannelSettings",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Client id={self.id} yclients_id={self.yclients_client_id!r} "
            f"preferred={self.preferred_channel!r}>"
        )


class ClientChannelSettings(Base, TimestampMixin):
    """
    Per-channel notification settings for a client.
    UNIQUE(client_id, channel) ensures one settings row per channel.
    """

    __tablename__ = "client_channel_settings"
    __table_args__ = (
        UniqueConstraint("client_id", "channel", name="uq_client_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # JSON array of notification types, e.g. ["all"] or ["new_appointment", "reminder_24h"]
    notification_types: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=lambda: ["all"]
    )
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Europe/Moscow"
    )

    # Relationships
    client: Mapped[Client] = relationship("Client", back_populates="channel_settings")

    def __repr__(self) -> str:
        return (
            f"<ClientChannelSettings client_id={self.client_id} "
            f"channel={self.channel!r} enabled={self.is_enabled}>"
        )
