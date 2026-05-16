"""
app/api/health.py — Health check endpoint.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.database import get_engine
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["monitoring"])


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """
    Check connectivity to PostgreSQL, Redis, and external APIs.
    Returns overall status: healthy | degraded | unhealthy
    """
    services: dict[str, dict[str, Any]] = {}

    # PostgreSQL
    services["postgresql"] = await _check_postgres()

    # Redis
    services["redis"] = await _check_redis()

    # External APIs (lightweight checks)
    services["yclients_api"] = await _check_yclients()
    services["telegram_api"] = await _check_telegram()

    # Determine overall status
    statuses = [s["status"] for s in services.values()]
    if all(s == "ok" for s in statuses):
        overall = "healthy"
    elif any(s == "error" for s in statuses):
        overall = "degraded"
    else:
        overall = "unhealthy"

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": services,
    }


async def _check_postgres() -> dict[str, Any]:
    start = time.monotonic()
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency = round((time.monotonic() - start) * 1000, 1)
        return {"status": "ok", "latency_ms": latency}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:100]}


async def _check_redis() -> dict[str, Any]:
    start = time.monotonic()
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings
        settings = get_settings()
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        latency = round((time.monotonic() - start) * 1000, 1)
        return {"status": "ok", "latency_ms": latency}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:100]}


async def _check_yclients() -> dict[str, Any]:
    start = time.monotonic()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("https://api.yclients.com/api/v1/")
        latency = round((time.monotonic() - start) * 1000, 1)
        # Any response (even 401) means the API is reachable
        return {"status": "ok", "latency_ms": latency}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:100]}


async def _check_telegram() -> dict[str, Any]:
    start = time.monotonic()
    try:
        import httpx
        from app.config import get_settings
        settings = get_settings()
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
        latency = round((time.monotonic() - start) * 1000, 1)
        if response.status_code == 200:
            return {"status": "ok", "latency_ms": latency}
        return {"status": "error", "error": f"HTTP {response.status_code}"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:100]}
