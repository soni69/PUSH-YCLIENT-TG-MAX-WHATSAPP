"""
app/schemas/task.py — Pydantic schemas for TaskQueue and ActionDedup.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.enums import TaskStatus


class TaskQueueRead(BaseModel):
    id: int
    task_id: str
    task_type: str
    payload: dict[str, Any]
    status: TaskStatus
    attempts: int
    max_attempts: int
    next_retry_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActionDedupRead(BaseModel):
    id: int
    appointment_id: str
    action: str
    client_id: str
    channel: str
    executed_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}
