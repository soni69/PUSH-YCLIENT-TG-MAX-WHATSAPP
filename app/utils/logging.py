"""
app/utils/logging.py — Structured JSON logging via structlog.

Provides a pre-configured structlog logger that emits JSON lines to stdout,
compatible with Docker log drivers and log-aggregation systems (Loki, ELK, etc.).

Usage
-----
    from app.utils.logging import get_logger

    logger = get_logger(__name__)
    logger.info("notification_sent", client_id="42", channel="telegram")
    logger.error("delivery_failed", client_id="42", channel="whatsapp", error=str(exc))

JSON output example
-------------------
    {
        "timestamp": "2024-05-01T12:00:00.123456Z",
        "level": "info",
        "service": "yclients-notification-bot",
        "event": "notification_sent",
        "client_id": "42",
        "channel": "telegram",
        "logger": "app.services.notification_service"
    }
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger


# ── Custom processors ─────────────────────────────────────────────────────────

def _add_service_name(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Inject a static 'service' field into every log record."""
    event_dict.setdefault("service", "yclients-notification-bot")
    return event_dict


def _rename_event_key(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Rename structlog's default 'event' key to 'event' (no-op here, but
    kept as an explicit hook for future renaming if needed).
    """
    return event_dict


def _drop_color_message(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Remove uvicorn's 'color_message' key to keep JSON output clean."""
    event_dict.pop("color_message", None)
    return event_dict


# ── Setup ─────────────────────────────────────────────────────────────────────

def configure_logging(log_level: str = "INFO") -> None:
    """
    Configure structlog and the standard-library logging bridge.

    Call this once at application startup (e.g. in app/main.py lifespan).

    Parameters
    ----------
    log_level:
        One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        Defaults to INFO.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure stdlib logging so that third-party libraries (uvicorn,
    # sqlalchemy, celery, aiogram) also emit structured JSON.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # Silence overly verbose loggers in production.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    shared_processors: list[Any] = [
        # Add log level as a string field.
        structlog.stdlib.add_log_level,
        # Add ISO-8601 timestamp.
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Inject service name.
        _add_service_name,
        # Remove uvicorn colour codes.
        _drop_color_message,
        # Render exception info as a string.
        structlog.processors.format_exc_info,
        # Render stack info.
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=shared_processors
        + [
            # Bridge structlog → stdlib so that stdlib handlers pick it up.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Attach a JSON formatter to the root handler.
    formatter = structlog.stdlib.ProcessorFormatter(
        # Final renderer: emit compact JSON.
        processor=structlog.processors.JSONRenderer(),
        # Processors applied to records that come from stdlib loggers.
        foreign_pre_chain=shared_processors,
    )

    root_handler = logging.StreamHandler(sys.stdout)
    root_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Remove any handlers added by basicConfig to avoid duplicate output.
    root_logger.handlers.clear()
    root_logger.addHandler(root_handler)
    root_logger.setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Return a structlog BoundLogger bound to *name*.

    Parameters
    ----------
    name:
        Typically ``__name__`` of the calling module.
        If omitted, returns the root logger.

    Returns
    -------
    structlog.stdlib.BoundLogger
        A logger that emits structured JSON records.
    """
    return structlog.get_logger(name)
