"""
app/api/admin.py — AdminPanel REST API with JWT authentication.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.client import Client, ClientChannelSettings
from app.models.notification import NotificationLog
from app.models.template import NotificationTemplate
from app.schemas.enums import Channel, DeliveryStatus, NotificationType
from app.schemas.notification import NotificationLogFilter, SendNotificationRequest
from app.schemas.template import TemplateUpdate, TemplateValidationResult
from app.utils.logging import get_logger
from app.utils.security import create_access_token, decode_access_token

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/admin/token")

import pathlib
_templates_dir = pathlib.Path(__file__).parent.parent / "admin" / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


# ── Authentication ────────────────────────────────────────────────────────────

@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> dict[str, str]:
    """Authenticate admin and return JWT token."""
    settings = get_settings()
    if (
        form_data.username != settings.admin_username
        or form_data.password != settings.admin_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=form_data.username)
    return {"access_token": token, "token_type": "bearer"}


async def get_current_admin(token: str = Depends(oauth2_scheme)) -> str:
    """Dependency: validate JWT and return admin username."""
    username = decode_access_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> HTMLResponse:
    """Admin dashboard with notification statistics."""
    stats = await _get_stats(db)
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "stats": stats, "admin": admin},
    )


@router.get("/stats")
async def get_stats_api(
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> dict[str, Any]:
    """Return notification statistics as JSON."""
    return await _get_stats(db)


async def _get_stats(db: AsyncSession) -> dict[str, Any]:
    """Compute notification statistics."""
    # Total sent in last 24h
    cutoff_24h = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)

    result = await db.execute(
        select(
            NotificationLog.channel,
            NotificationLog.status,
            func.count(NotificationLog.id).label("count"),
        )
        .where(NotificationLog.created_at >= cutoff_24h)
        .group_by(NotificationLog.channel, NotificationLog.status)
    )
    rows = result.all()

    by_channel: dict[str, dict[str, int]] = {}
    total_sent = 0
    total_failed = 0

    for row in rows:
        channel = row.channel
        stat_status = row.status
        count = row.count

        if channel not in by_channel:
            by_channel[channel] = {"sent": 0, "failed": 0, "total": 0}

        by_channel[channel]["total"] += count
        if stat_status in ("sent", "delivered"):
            by_channel[channel]["sent"] += count
            total_sent += count
        elif stat_status == "failed":
            by_channel[channel]["failed"] += count
            total_failed += count

    total = total_sent + total_failed
    success_rate = round(total_sent / total * 100, 1) if total > 0 else 0

    return {
        "total_sent_today": total_sent,
        "total_failed_today": total_failed,
        "success_rate": success_rate,
        "by_channel": by_channel,
    }


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> list[dict[str, Any]]:
    """List all notification templates."""
    result = await db.execute(
        select(NotificationTemplate).order_by(
            NotificationTemplate.notification_type,
            NotificationTemplate.channel,
        )
    )
    templates_list = result.scalars().all()
    return [
        {
            "id": t.id,
            "notification_type": t.notification_type,
            "channel": t.channel,
            "language": t.language,
            "body_template": t.body_template,
            "is_active": t.is_active,
            "is_default": t.is_default,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in templates_list
    ]


@router.get("/templates/{template_id}")
async def get_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> dict[str, Any]:
    """Get a single template by ID."""
    result = await db.execute(
        select(NotificationTemplate).where(NotificationTemplate.id == template_id)
    )
    tmpl = result.scalar_one_or_none()
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {
        "id": tmpl.id,
        "notification_type": tmpl.notification_type,
        "channel": tmpl.channel,
        "language": tmpl.language,
        "body_template": tmpl.body_template,
        "is_active": tmpl.is_active,
    }


@router.put("/templates/{template_id}")
async def update_template(
    template_id: int,
    update_data: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> dict[str, Any]:
    """Update a template. Invalidates Redis cache."""
    result = await db.execute(
        select(NotificationTemplate).where(NotificationTemplate.id == template_id)
    )
    tmpl = result.scalar_one_or_none()
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found")

    if update_data.body_template is not None:
        # Validate before saving
        from app.services.template_engine import TemplateEngine
        engine = TemplateEngine(db)
        invalid_vars = engine.validate_template(update_data.body_template)
        if invalid_vars:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid template variables: {invalid_vars}",
            )
        tmpl.body_template = update_data.body_template

    if update_data.is_active is not None:
        tmpl.is_active = update_data.is_active

    if update_data.subject is not None:
        tmpl.subject = update_data.subject

    await db.commit()

    # Invalidate cache
    from app.services.template_engine import TemplateEngine
    engine = TemplateEngine(db)
    await engine.invalidate_cache(tmpl.notification_type, tmpl.channel, tmpl.language)

    logger.info(
        "template_updated",
        template_id=template_id,
        admin=admin,
    )
    return {"status": "updated", "id": template_id}


@router.post("/templates/validate")
async def validate_template(
    body: dict[str, str],
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> TemplateValidationResult:
    """Validate a template body and return invalid variables."""
    from app.services.template_engine import TemplateEngine
    engine = TemplateEngine(db)
    template_body = body.get("body_template", "")
    invalid = engine.validate_template(template_body)
    return TemplateValidationResult(
        is_valid=len(invalid) == 0,
        invalid_variables=invalid,
    )


# ── Notification log ──────────────────────────────────────────────────────────

@router.get("/notifications")
async def list_notifications(
    channel: str | None = None,
    notification_type: str | None = None,
    stat_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> dict[str, Any]:
    """List notification history with optional filters."""
    query = select(NotificationLog).order_by(NotificationLog.created_at.desc())

    if channel:
        query = query.where(NotificationLog.channel == channel)
    if notification_type:
        query = query.where(NotificationLog.notification_type == notification_type)
    if stat_status:
        query = query.where(NotificationLog.status == stat_status)

    result = await db.execute(query.limit(limit).offset(offset))
    logs = result.scalars().all()

    return {
        "items": [
            {
                "id": log.id,
                "client_id": log.client_id,
                "channel": log.channel,
                "notification_type": log.notification_type,
                "appointment_id": log.appointment_id,
                "status": log.status,
                "error_message": log.error_message,
                "sent_at": log.sent_at.isoformat() if log.sent_at else None,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
        "limit": limit,
        "offset": offset,
    }


# ── Clients ───────────────────────────────────────────────────────────────────

@router.get("/clients")
async def list_clients(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> dict[str, Any]:
    """List registered clients with their channel bindings."""
    result = await db.execute(
        select(Client)
        .where(Client.is_active.is_(True))
        .order_by(Client.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    clients = result.scalars().all()

    return {
        "items": [
            {
                "id": c.id,
                "yclients_client_id": c.yclients_client_id,
                "telegram_id": c.telegram_id,
                "max_user_id": c.max_user_id,
                "has_whatsapp": c.whatsapp_phone_hash is not None,
                "preferred_channel": c.preferred_channel,
                "created_at": c.created_at.isoformat(),
            }
            for c in clients
        ],
        "limit": limit,
        "offset": offset,
    }


@router.post("/clients/{client_id}/deactivate-channel")
async def deactivate_client_channel(
    client_id: str,
    channel: str,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> dict[str, str]:
    """Deactivate a specific channel for a client."""
    from app.services.client_registry import ClientRegistry
    registry = ClientRegistry(db)
    await registry.deactivate_channel(
        client_id=client_id,
        channel=Channel(channel),
        reason=f"deactivated_by_admin:{admin}",
    )
    await db.commit()
    return {"status": "deactivated"}


# ── Test send ─────────────────────────────────────────────────────────────────

@router.post("/test-send")
async def test_send(
    request_data: SendNotificationRequest,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(get_current_admin),
) -> dict[str, Any]:
    """Manually send a test notification to a client."""
    from app.services.yclients_client import get_yclients_client
    from app.services.notification_service import NotificationService
    from app.schemas.yclients import AppointmentData, ClientInfo
    from datetime import datetime, timezone

    yclients = get_yclients_client()
    client_info = await yclients.get_client(int(request_data.client_id))
    if client_info is None:
        raise HTTPException(status_code=404, detail="Client not found in YClients")

    # Create a dummy appointment for test
    dummy_appointment = AppointmentData(
        id=0,
        company_id=0,
        client_id=int(request_data.client_id),
        staff_id=0,
        services=[],
        appointment_datetime=datetime.now(timezone.utc),
    )

    service = NotificationService(db)
    results = await service.send_appointment_notification(
        appointment=dummy_appointment,
        client_info=client_info,
        notification_type=request_data.notification_type,
    )
    await db.commit()

    logger.info(
        "test_notification_sent",
        client_id=request_data.client_id,
        notification_type=request_data.notification_type.value,
        admin=admin,
    )

    return {
        "status": "sent",
        "results": [r.model_dump() for r in results],
    }
