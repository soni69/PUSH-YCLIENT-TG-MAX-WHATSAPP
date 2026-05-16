"""
app/api/webhook.py — Webhook endpoints for YClients, Telegram, WhatsApp, and MAX.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings
from app.schemas.yclients import YClientsWebhookPayload
from app.utils.logging import get_logger
from app.utils.security import validate_webhook_signature

logger = get_logger(__name__)
router = APIRouter(tags=["webhooks"])
limiter = Limiter(key_func=get_remote_address)


# ── YClients webhook ──────────────────────────────────────────────────────────

@router.post("/webhook/yclients")
@limiter.limit("100/minute")
async def yclients_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_yclients_signature: str | None = Header(default=None, alias="X-Yclients-Signature"),
) -> dict[str, str]:
    """
    Receive YClients events.
    - Validates HMAC-SHA256 signature
    - Queues processing task asynchronously
    - Returns 200 within 5 seconds
    """
    settings = get_settings()
    body = await request.body()

    # Validate signature if secret is configured
    if settings.yclients_webhook_secret and x_yclients_signature:
        if not validate_webhook_signature(
            payload=body,
            signature_header=x_yclients_signature,
            secret=settings.yclients_webhook_secret,
        ):
            logger.warning(
                "webhook_invalid_signature",
                remote_addr=request.client.host if request.client else "unknown",
            )
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Queue the task asynchronously — respond immediately
    background_tasks.add_task(_queue_yclients_event, payload_data)

    logger.info(
        "yclients_webhook_received",
        resource=payload_data.get("resource"),
        status=payload_data.get("status"),
        resource_id=payload_data.get("resource_id"),
    )
    return {"status": "accepted"}


async def _queue_yclients_event(payload_data: dict[str, Any]) -> None:
    """Queue a YClients event for async processing."""
    try:
        from app.tasks.notification_tasks import send_notification_task
        from app.database import get_session_factory
        from app.models.task import TaskQueue
        import uuid

        task_id = str(uuid.uuid4())

        # Record in task_queue for idempotency
        factory = get_session_factory()
        async with factory() as db:
            task_record = TaskQueue(
                task_id=task_id,
                task_type="yclients_webhook",
                payload=payload_data,
                status="pending",
            )
            db.add(task_record)
            await db.commit()

        # Queue Celery task
        from app.tasks.notification_tasks import celery_app
        celery_app.send_task(
            "app.tasks.notification_tasks.process_yclients_event_task",
            args=[payload_data],
            task_id=task_id,
            queue="notifications",
        )
    except Exception as exc:
        logger.error("webhook_queue_error", error=str(exc))


# ── Telegram webhook ──────────────────────────────────────────────────────────

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> dict[str, str]:
    """Receive Telegram Bot API updates."""
    try:
        update_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        from app.adapters.telegram_adapter import get_telegram_adapter
        adapter = get_telegram_adapter()
        await adapter.process_update(update_data)
    except Exception as exc:
        logger.error("telegram_webhook_error", error=str(exc))

    return {"status": "ok"}


# ── WhatsApp webhook ──────────────────────────────────────────────────────────

@router.get("/webhook/whatsapp")
async def whatsapp_webhook_verify(
    hub_mode: str | None = None,
    hub_verify_token: str | None = None,
    hub_challenge: str | None = None,
) -> Response:
    """WhatsApp webhook verification (GET request from Meta)."""
    from app.adapters.whatsapp_adapter import get_whatsapp_adapter
    adapter = get_whatsapp_adapter()

    challenge = adapter.verify_webhook(
        mode=hub_mode or "",
        token=hub_verify_token or "",
        challenge=hub_challenge or "",
    )
    if challenge:
        return Response(content=challenge, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request) -> dict[str, str]:
    """Receive WhatsApp Business Cloud API events."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        from app.adapters.whatsapp_adapter import get_whatsapp_adapter
        adapter = get_whatsapp_adapter()
        await adapter.handle_webhook(payload)
    except Exception as exc:
        logger.error("whatsapp_webhook_error", error=str(exc))

    return {"status": "ok"}
