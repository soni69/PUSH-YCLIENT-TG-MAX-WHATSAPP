"""
app/main.py — FastAPI application entry point.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.utils.logging import configure_logging, get_logger


def _check_required_env_vars() -> None:
    """Exit with code 1 if any required environment variable is missing."""
    try:
        from app.config import get_settings
        get_settings()  # This will raise ValidationError if vars are missing
    except Exception as exc:
        print(f"[FATAL] Missing or invalid environment variable: {exc}", file=sys.stderr)
        sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    settings_obj = None
    try:
        from app.config import get_settings
        settings_obj = get_settings()
    except Exception:
        pass

    log_level = settings_obj.log_level if settings_obj else "INFO"
    configure_logging(log_level)
    logger = get_logger(__name__)

    logger.info("application_starting")

    # Run database migrations
    try:
        import subprocess
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("database_migrations_applied")
        else:
            logger.warning("database_migrations_warning", stderr=result.stderr[:200])
    except Exception as exc:
        logger.warning("database_migrations_skipped", error=str(exc))

    # Seed default templates
    try:
        from app.database import get_session_factory
        from app.services.template_engine import seed_default_templates
        factory = get_session_factory()
        async with factory() as db:
            await seed_default_templates(db)
        logger.info("templates_seeded")
    except Exception as exc:
        logger.warning("templates_seed_failed", error=str(exc))

    # Start MAX long-polling in background
    try:
        from app.adapters.max_adapter import get_max_adapter
        max_adapter = get_max_adapter()
        await max_adapter.start_polling()
        logger.info("max_polling_started")
    except Exception as exc:
        logger.warning("max_polling_start_failed", error=str(exc))

    logger.info("application_started")
    yield

    # Shutdown
    logger.info("application_shutting_down")

    try:
        from app.adapters.telegram_adapter import get_telegram_adapter
        await get_telegram_adapter().close()
    except Exception:
        pass

    try:
        from app.adapters.whatsapp_adapter import get_whatsapp_adapter
        await get_whatsapp_adapter().close()
    except Exception:
        pass

    try:
        from app.adapters.max_adapter import get_max_adapter
        await get_max_adapter().close()
    except Exception:
        pass

    try:
        from app.database import close_engine
        await close_engine()
    except Exception:
        pass

    logger.info("application_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    _check_required_env_vars()

    from app.config import get_settings
    settings = get_settings()

    app = FastAPI(
        title="YClients Notification Bot",
        description="Multi-channel notification bot replacing YClients push notifications",
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting middleware
    from app.api.webhook import limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────────
    from app.api.webhook import router as webhook_router
    from app.api.health import router as health_router
    from app.api.metrics import router as metrics_router
    from app.api.admin import router as admin_router

    app.include_router(webhook_router)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(admin_router)

    # ── Root endpoint ─────────────────────────────────────────────────────────
    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "YClients Notification Bot",
            "version": "1.0.0",
            "status": "running",
        }

    return app


# Create the application instance
app = create_app()
