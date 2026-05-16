"""
app/adapters/whatsapp_adapter.py — WhatsApp Business Cloud API adapter.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.adapters.base import BaseAdapter
from app.config import get_settings
from app.schemas.enums import Channel, DeliveryStatus
from app.schemas.notification import DeliveryResult
from app.services.template_engine import RenderedMessage
from app.utils.logging import get_logger

logger = get_logger(__name__)

# WhatsApp template names (must be pre-approved in Meta Business Manager)
WA_TEMPLATE_MAP = {
    "new_appointment": "appointment_created",
    "confirmed": "appointment_confirmed",
    "cancelled": "appointment_cancelled",
    "in_progress": "appointment_in_progress",
    "changed": "appointment_changed",
    "reminder_24h": "appointment_reminder_24h",
    "reminder_2h": "appointment_reminder_2h",
    "birthday": "birthday_greeting",
}


class WhatsAppAdapter(BaseAdapter):
    """
    Sends notifications via WhatsApp Business Cloud API.

    - Uses template messages for first contact (no active session)
    - Uses free-form interactive messages within 24h session window
    - Supports interactive/button messages (max 3 buttons)
    - Deactivates channel on invalid phone number errors
    """

    GRAPH_API_VERSION = "v18.0"

    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.whatsapp_api_token
        self._phone_number_id = settings.whatsapp_phone_number_id
        self._business_account_id = settings.whatsapp_business_account_id
        self._verify_token = settings.whatsapp_verify_token
        self._base_url = (
            f"https://graph.facebook.com/{self.GRAPH_API_VERSION}"
            f"/{self._phone_number_id}/messages"
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def send_notification(
        self,
        recipient_id: str | int,
        message: RenderedMessage,
        appointment_id: str | None = None,
    ) -> DeliveryResult:
        """
        Send a notification to a WhatsApp number.
        Uses template message by default (safe for first contact).
        """
        phone = str(recipient_id)
        template_name = WA_TEMPLATE_MAP.get(message.notification_type)

        if template_name:
            return await self.send_template_message(
                phone=phone,
                template_name=template_name,
                body_text=message.text,
                appointment_id=appointment_id,
            )
        else:
            # Fallback to text message
            return await self._send_text_message(phone, message.text)

    async def send_template_message(
        self,
        phone: str,
        template_name: str,
        body_text: str,
        appointment_id: str | None = None,
    ) -> DeliveryResult:
        """Send a pre-approved WhatsApp template message."""
        # Build components with body text as parameter
        components = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": body_text[:1024]},
                ],
            }
        ]

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": self._normalise_phone(phone),
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "ru"},
                "components": components,
            },
        }

        return await self._send(phone, payload)

    async def send_interactive_message(
        self,
        phone: str,
        body: str,
        buttons: list[dict[str, str]],
    ) -> DeliveryResult:
        """
        Send an interactive message with reply buttons (max 3).
        Used within a 24-hour session window.
        """
        # Truncate to WhatsApp limits
        buttons = buttons[:3]
        wa_buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": btn.get("id", f"btn_{i}"),
                    "title": btn.get("title", "")[:20],
                },
            }
            for i, btn in enumerate(buttons)
        ]

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": self._normalise_phone(phone),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body[:1024]},
                "action": {"buttons": wa_buttons},
            },
        }

        return await self._send(phone, payload)

    async def _send_text_message(self, phone: str, text: str) -> DeliveryResult:
        """Send a plain text message."""
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": self._normalise_phone(phone),
            "type": "text",
            "text": {"body": text[:4096]},
        }
        return await self._send(phone, payload)

    async def _send(self, phone: str, payload: dict[str, Any]) -> DeliveryResult:
        """Execute the API call and handle errors."""
        client = await self._get_client()
        try:
            response = await client.post(self._base_url, json=payload)
            data = response.json()

            if response.status_code == 200:
                messages = data.get("messages", [])
                message_id = messages[0].get("id") if messages else None
                logger.info(
                    "whatsapp_message_sent",
                    phone_masked=self._mask_phone(phone),
                    message_id=message_id,
                )
                return DeliveryResult(
                    channel=Channel.WHATSAPP,
                    status=DeliveryStatus.SENT,
                    message_id=message_id,
                )

            # Handle specific error codes
            error = data.get("error", {})
            error_code = error.get("code", 0)
            error_msg = error.get("message", str(data))

            logger.error(
                "whatsapp_send_error",
                phone_masked=self._mask_phone(phone),
                status_code=response.status_code,
                error_code=error_code,
                error_message=error_msg,
            )

            # Error 131026: phone not on WhatsApp
            if error_code in (131026, 131047):
                return DeliveryResult(
                    channel=Channel.WHATSAPP,
                    status=DeliveryStatus.FAILED,
                    error="phone_not_on_whatsapp",
                )

            return DeliveryResult(
                channel=Channel.WHATSAPP,
                status=DeliveryStatus.FAILED,
                error=f"{error_code}: {error_msg}",
            )

        except httpx.RequestError as exc:
            logger.error("whatsapp_request_error", error=str(exc))
            return DeliveryResult(
                channel=Channel.WHATSAPP,
                status=DeliveryStatus.FAILED,
                error=str(exc),
            )

    async def handle_webhook(self, payload: dict[str, Any]) -> None:
        """
        Process incoming WhatsApp webhook (status updates, incoming messages).
        """
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # Handle delivery status updates
                for status in value.get("statuses", []):
                    await self._handle_status_update(status)

                # Handle incoming messages
                for msg in value.get("messages", []):
                    await self._handle_incoming_message(msg, value)

    async def _handle_status_update(self, status: dict[str, Any]) -> None:
        """Update notification_log with delivery status."""
        message_id = status.get("id")
        wa_status = status.get("status")  # sent, delivered, read, failed

        status_map = {
            "sent": DeliveryStatus.SENT,
            "delivered": DeliveryStatus.DELIVERED,
            "read": DeliveryStatus.DELIVERED,
            "failed": DeliveryStatus.FAILED,
        }
        delivery_status = status_map.get(wa_status, DeliveryStatus.SENT)

        logger.info(
            "whatsapp_status_update",
            message_id=message_id,
            status=wa_status,
        )

        # Update notification_log — done via NotificationService
        from app.services.notification_service import update_delivery_status
        await update_delivery_status(
            message_id=message_id,
            channel=Channel.WHATSAPP,
            status=delivery_status,
        )

    async def _handle_incoming_message(
        self, msg: dict[str, Any], value: dict[str, Any]
    ) -> None:
        """Handle an incoming WhatsApp message (button reply or text)."""
        msg_type = msg.get("type")
        from_phone = msg.get("from", "")

        if msg_type == "interactive":
            interactive = msg.get("interactive", {})
            if interactive.get("type") == "button_reply":
                button_id = interactive["button_reply"].get("id", "")
                parts = button_id.split(":", 1)
                if len(parts) == 2:
                    action, appointment_id = parts
                    from app.services.action_handler import handle_client_action
                    await handle_client_action(
                        action=action,
                        appointment_id=appointment_id,
                        client_channel_id=from_phone,
                        channel=Channel.WHATSAPP,
                    )

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        """Verify WhatsApp webhook subscription."""
        if mode == "subscribe" and token == self._verify_token:
            return challenge
        return None

    @staticmethod
    def _normalise_phone(phone: str) -> str:
        """Remove non-digit characters except leading +."""
        return "".join(c for c in phone if c.isdigit())

    @staticmethod
    def _mask_phone(phone: str) -> str:
        if len(phone) < 7:
            return phone
        return phone[:4] + "***" + phone[-4:]


# Module-level singleton
_whatsapp_adapter: WhatsAppAdapter | None = None


def get_whatsapp_adapter() -> WhatsAppAdapter:
    global _whatsapp_adapter
    if _whatsapp_adapter is None:
        _whatsapp_adapter = WhatsAppAdapter()
    return _whatsapp_adapter
