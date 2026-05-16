"""
app/api/metrics.py — Prometheus metrics endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

router = APIRouter(tags=["monitoring"])

# ── Prometheus metrics ────────────────────────────────────────────────────────

notifications_sent_total = Counter(
    "notifications_sent_total",
    "Total number of notifications sent",
    ["channel", "notification_type", "status"],
)

notification_send_duration_seconds = Histogram(
    "notification_send_duration_seconds",
    "Time spent sending a notification",
    ["channel"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

yclients_api_requests_total = Counter(
    "yclients_api_requests_total",
    "Total YClients API requests",
    ["method", "endpoint", "status"],
)

webhook_events_total = Counter(
    "webhook_events_total",
    "Total webhook events received",
    ["source", "event_type"],
)

task_queue_size = Counter(
    "task_queue_processed_total",
    "Total Celery tasks processed",
    ["task_type", "status"],
)


@router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


def record_notification_sent(
    channel: str,
    notification_type: str,
    status: str,
    duration_seconds: float,
) -> None:
    """Record a notification send event."""
    notifications_sent_total.labels(
        channel=channel,
        notification_type=notification_type,
        status=status,
    ).inc()
    notification_send_duration_seconds.labels(channel=channel).observe(duration_seconds)
