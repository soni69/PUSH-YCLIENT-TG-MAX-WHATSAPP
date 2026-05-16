"""
tests/conftest.py — Shared pytest fixtures.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

# Set test environment variables before importing app modules
os.environ.setdefault("YCLIENTS_API_TOKEN", "test_token")
os.environ.setdefault("YCLIENTS_COMPANY_ID", "12345")
os.environ.setdefault("YCLIENTS_WEBHOOK_SECRET", "test_secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:ABCtest")
os.environ.setdefault("WHATSAPP_API_TOKEN", "test_wa_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "1234567890")
os.environ.setdefault("WHATSAPP_BUSINESS_ACCOUNT_ID", "9876543210")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_verify")
os.environ.setdefault("MAX_BOT_TOKEN", "test_max_token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "testpassword")
os.environ.setdefault("ADMIN_JWT_SECRET", "test_jwt_secret_that_is_long_enough_32chars")
os.environ.setdefault("ENVIRONMENT", "development")


@pytest.fixture
def mock_db():
    """Mock AsyncSession."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    return redis
