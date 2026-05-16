"""
app/schemas/template.py — Pydantic schemas for NotificationTemplate.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import Channel, NotificationType


class TemplateBase(BaseModel):
    notification_type: NotificationType
    channel: Channel
    language: str = "ru"
    subject: str | None = None
    body_template: str = Field(..., min_length=1)
    is_active: bool = True
    is_default: bool = False


class TemplateCreate(TemplateBase):
    created_by: str | None = None


class TemplateUpdate(BaseModel):
    subject: str | None = None
    body_template: str | None = None
    is_active: bool | None = None


class TemplateRead(TemplateBase):
    id: int
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateValidationResult(BaseModel):
    is_valid: bool
    invalid_variables: list[str] = []
    preview: str | None = None
