"""
app/schemas/client.py — Pydantic schemas for Client and ClientChannelSettings.
"""

from __future__ import annotations

from datetime import datetime, time

from pydantic import BaseModel, Field

from app.schemas.enums import Channel


class ChannelSettingsBase(BaseModel):
    channel: Channel
    is_enabled: bool = True
    notification_types: list[str] = Field(default_factory=lambda: ["all"])
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    timezone: str = "Europe/Moscow"


class ChannelSettingsCreate(ChannelSettingsBase):
    pass


class ChannelSettingsUpdate(BaseModel):
    is_enabled: bool | None = None
    notification_types: list[str] | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    timezone: str | None = None


class ChannelSettingsRead(ChannelSettingsBase):
    id: int
    client_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClientBase(BaseModel):
    yclients_client_id: str
    preferred_channel: Channel = Channel.TELEGRAM
    is_active: bool = True


class ClientCreate(ClientBase):
    telegram_id: int | None = None
    whatsapp_phone_hash: str | None = None
    whatsapp_phone_enc: str | None = None
    max_user_id: str | None = None


class ClientUpdate(BaseModel):
    telegram_id: int | None = None
    whatsapp_phone_hash: str | None = None
    whatsapp_phone_enc: str | None = None
    max_user_id: str | None = None
    preferred_channel: Channel | None = None
    is_active: bool | None = None


class ClientRead(ClientBase):
    id: int
    telegram_id: int | None = None
    max_user_id: str | None = None
    channel_settings: list[ChannelSettingsRead] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LinkChannelRequest(BaseModel):
    """Request to link a messenger account by phone number."""
    phone: str = Field(..., description="Phone number in E.164 format, e.g. +79001234567")


class UnsubscribeRequest(BaseModel):
    channel: Channel
