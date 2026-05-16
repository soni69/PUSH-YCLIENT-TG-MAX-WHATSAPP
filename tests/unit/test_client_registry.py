"""
tests/unit/test_client_registry.py — Unit tests for ClientRegistry.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.enums import Channel
from app.services.client_registry import ClientRegistry
from app.utils.security import hash_phone


@pytest.fixture
def registry(mock_db):
    return ClientRegistry(db=mock_db)


class TestFindByPhoneHash:
    @pytest.mark.asyncio
    async def test_returns_client_when_found(self, registry, mock_db):
        mock_client = MagicMock()
        mock_client.yclients_client_id = "42"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_client
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await registry.find_by_phone_hash("+79001234567")
        assert result is mock_client

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, registry, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await registry.find_by_phone_hash("+79001234567")
        assert result is None


class TestGetClient:
    @pytest.mark.asyncio
    async def test_returns_active_client(self, registry, mock_db):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_client
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await registry.get_client("42")
        assert result is mock_client

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_client(self, registry, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await registry.get_client("nonexistent")
        assert result is None


class TestHashPhoneIntegration:
    def test_phone_hash_used_for_lookup(self):
        """Verify that hash_phone produces consistent results for registry lookups."""
        phone = "+79001234567"
        h1 = hash_phone(phone)
        h2 = hash_phone(phone)
        assert h1 == h2
        assert len(h1) == 64
