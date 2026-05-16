"""
app/adapters/base.py — Abstract base adapter for messenger integrations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.notification import DeliveryResult
from app.services.template_engine import RenderedMessage


class BaseAdapter(ABC):
    """
    Abstract base class for all messenger adapters.
    Each adapter must implement send_notification.
    """

    @abstractmethod
    async def send_notification(
        self,
        recipient_id: str | int,
        message: RenderedMessage,
        appointment_id: str | None = None,
    ) -> DeliveryResult:
        """Send a notification to the given recipient."""
        ...
