"""
app/services/client_registry.py — ClientRegistry: manages client-to-channel bindings.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client, ClientChannelSettings
from app.schemas.client import ChannelSettingsRead, ClientRead
from app.schemas.enums import Channel
from app.services.yclients_client import get_yclients_client
from app.utils.logging import get_logger
from app.utils.security import hash_phone, mask_phone

logger = get_logger(__name__)


class ClientRegistry:
    """
    Manages the mapping between YClients client IDs and messenger identifiers.

    All phone-based lookups use SHA-256 hashes to avoid storing raw numbers.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_client(self, yclients_client_id: str) -> Client | None:
        """Fetch a client by their YClients ID."""
        result = await self._db.execute(
            select(Client).where(
                Client.yclients_client_id == yclients_client_id,
                Client.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_client(self, yclients_client_id: str) -> Client:
        """Return existing client or create a new one."""
        client = await self.get_client(yclients_client_id)
        if client is None:
            client = Client(yclients_client_id=yclients_client_id)
            self._db.add(client)
            await self._db.flush()
            logger.info("client_created", yclients_client_id=yclients_client_id)
        return client

    async def find_by_phone_hash(self, phone: str) -> Client | None:
        """Find a client by phone number (hashed lookup)."""
        phone_hash = hash_phone(phone)
        result = await self._db.execute(
            select(Client).where(
                Client.whatsapp_phone_hash == phone_hash,
                Client.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def link_telegram(self, phone: str, telegram_id: int) -> Client | None:
        """
        Link a Telegram ID to a client identified by phone number.
        Looks up the client in YClients first, then saves the binding.
        """
        # Try to find existing client by phone hash
        client = await self.find_by_phone_hash(phone)

        if client is None:
            # Look up in YClients API
            yclients = get_yclients_client()
            client_info = await yclients.find_client_by_phone(phone)
            if client_info is None:
                logger.warning(
                    "telegram_link_client_not_found",
                    phone_masked=mask_phone(phone),
                )
                return None
            client = await self.get_or_create_client(str(client_info.id))
            client.whatsapp_phone_hash = hash_phone(phone)
            client.whatsapp_phone_enc = mask_phone(phone)

        client.telegram_id = telegram_id
        if not client.preferred_channel:
            client.preferred_channel = Channel.TELEGRAM.value

        # Ensure channel settings exist
        await self._ensure_channel_settings(client, Channel.TELEGRAM)

        await self._db.flush()
        logger.info(
            "telegram_linked",
            yclients_client_id=client.yclients_client_id,
            telegram_id=telegram_id,
        )
        return client

    async def link_max(self, phone: str, max_user_id: str) -> Client | None:
        """
        Link a MAX user ID to a client identified by phone number.
        """
        client = await self.find_by_phone_hash(phone)

        if client is None:
            yclients = get_yclients_client()
            client_info = await yclients.find_client_by_phone(phone)
            if client_info is None:
                logger.warning(
                    "max_link_client_not_found",
                    phone_masked=mask_phone(phone),
                )
                return None
            client = await self.get_or_create_client(str(client_info.id))
            client.whatsapp_phone_hash = hash_phone(phone)
            client.whatsapp_phone_enc = mask_phone(phone)

        client.max_user_id = max_user_id
        await self._ensure_channel_settings(client, Channel.MAX)

        await self._db.flush()
        logger.info(
            "max_linked",
            yclients_client_id=client.yclients_client_id,
            max_user_id=max_user_id,
        )
        return client

    async def link_whatsapp(self, phone: str, yclients_client_id: str) -> Client | None:
        """
        Link a WhatsApp phone number to a client.
        Called when a WhatsApp message is received from a known phone.
        """
        client = await self.get_or_create_client(yclients_client_id)
        client.whatsapp_phone_hash = hash_phone(phone)
        client.whatsapp_phone_enc = mask_phone(phone)
        await self._ensure_channel_settings(client, Channel.WHATSAPP)
        await self._db.flush()
        logger.info(
            "whatsapp_linked",
            yclients_client_id=yclients_client_id,
            phone_masked=mask_phone(phone),
        )
        return client

    async def unsubscribe(self, client_id: str, channel: Channel) -> None:
        """Remove a channel binding for a client."""
        client = await self.get_client(client_id)
        if client is None:
            logger.warning("unsubscribe_client_not_found", client_id=client_id)
            return

        result = await self._db.execute(
            select(ClientChannelSettings).where(
                ClientChannelSettings.client_id == client.id,
                ClientChannelSettings.channel == channel.value,
            )
        )
        settings = result.scalar_one_or_none()
        if settings:
            await self._db.delete(settings)

        # Clear the messenger ID
        if channel == Channel.TELEGRAM:
            client.telegram_id = None
        elif channel == Channel.MAX:
            client.max_user_id = None
        elif channel == Channel.WHATSAPP:
            client.whatsapp_phone_hash = None
            client.whatsapp_phone_enc = None

        await self._db.flush()
        logger.info(
            "channel_unsubscribed",
            client_id=client_id,
            channel=channel.value,
        )

    async def deactivate_channel(
        self, client_id: str, channel: Channel, reason: str
    ) -> None:
        """Disable a channel (e.g. bot blocked, invalid number)."""
        client = await self.get_client(client_id)
        if client is None:
            return

        await self._db.execute(
            update(ClientChannelSettings)
            .where(
                ClientChannelSettings.client_id == client.id,
                ClientChannelSettings.channel == channel.value,
            )
            .values(is_enabled=False)
        )
        await self._db.flush()
        logger.warning(
            "channel_deactivated",
            client_id=client_id,
            channel=channel.value,
            reason=reason,
        )

    async def get_active_channels(
        self, client_id: str
    ) -> list[ClientChannelSettings]:
        """Return all enabled channel settings for a client."""
        client = await self.get_client(client_id)
        if client is None:
            return []

        result = await self._db.execute(
            select(ClientChannelSettings).where(
                ClientChannelSettings.client_id == client.id,
                ClientChannelSettings.is_enabled.is_(True),
            )
        )
        return list(result.scalars().all())

    async def _ensure_channel_settings(
        self, client: Client, channel: Channel
    ) -> ClientChannelSettings:
        """Create default channel settings if they don't exist."""
        result = await self._db.execute(
            select(ClientChannelSettings).where(
                ClientChannelSettings.client_id == client.id,
                ClientChannelSettings.channel == channel.value,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            settings = ClientChannelSettings(
                client_id=client.id,
                channel=channel.value,
                is_enabled=True,
                notification_types=["all"],
            )
            self._db.add(settings)
            await self._db.flush()
            return settings
        return existing
