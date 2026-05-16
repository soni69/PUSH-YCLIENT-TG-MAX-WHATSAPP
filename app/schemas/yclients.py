"""
app/schemas/yclients.py — Pydantic schemas for YClients API payloads.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class YClientsWebhookPayload(BaseModel):
    """Incoming webhook payload from YClients."""
    company_id: int
    resource: str          # "record", "client"
    resource_id: int
    status: str            # "create", "update", "delete"
    data: dict[str, Any] = Field(default_factory=dict)


class ServiceData(BaseModel):
    id: int
    title: str
    cost: float | None = None
    cost_per_unit: float | None = None
    first_cost: float | None = None
    amount: int = 1


class StaffData(BaseModel):
    id: int
    name: str
    specialization: str | None = None


class AppointmentData(BaseModel):
    """Appointment record from YClients API."""
    id: int
    company_id: int
    client_id: int | None = None
    staff_id: int
    staff: StaffData | None = None
    services: list[ServiceData] = Field(default_factory=list)
    date: str | None = None          # ISO date string
    datetime: str | None = None      # ISO datetime string
    status_id: int | None = None
    comment: str | None = None
    # Parsed datetime (populated by client code)
    appointment_datetime: datetime | None = None


class ClientInfo(BaseModel):
    """Client data from YClients API."""
    id: int
    name: str
    phone: str
    email: str | None = None
    birth_date: date | None = None
    comment: str | None = None


class YClientsAppointmentListResponse(BaseModel):
    success: bool
    data: list[AppointmentData] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class YClientsClientResponse(BaseModel):
    success: bool
    data: ClientInfo | None = None


class YClientsUpdateStatusRequest(BaseModel):
    """Request body for updating appointment status."""
    status_id: int
    comment: str | None = None
