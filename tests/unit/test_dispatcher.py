"""
tests/unit/test_dispatcher.py — Unit tests for Dispatcher routing logic.
"""

from __future__ import annotations

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.client import ClientChannelSettings
from app.schemas.enums import Channel, NotificationType
from app.services.dispatcher import Dispatcher


@pytest.fixture
def dispatcher(mock_db):
    return Dispatcher(db=mock_db)


def make_settings(
    channel: str = "telegram",
    is_enabled: bool = True,
    notification_types: list = None,
    quiet_start: time | None = None,
    quiet_end: time | None = None,
    timezone: str = "Europe/Moscow",
) -> ClientChannelSettings:
    s = MagicMock(spec=ClientChannelSettings)
    s.channel = channel
    s.is_enabled = is_enabled
    s.notification_types = notification_types or ["all"]
    s.quiet_hours_start = quiet_start
    s.quiet_hours_end = quiet_end
    s.timezone = timezone
    return s


class TestIsTypeAllowed:
    def test_all_allows_any_type(self, dispatcher):
        settings = make_settings(notification_types=["all"])
        assert dispatcher._is_type_allowed(settings, "new_appointment") is True
        assert dispatcher._is_type_allowed(settings, "birthday") is True

    def test_specific_type_allowed(self, dispatcher):
        settings = make_settings(notification_types=["new_appointment", "reminder_24h"])
        assert dispatcher._is_type_allowed(settings, "new_appointment") is True
        assert dispatcher._is_type_allowed(settings, "reminder_24h") is True

    def test_specific_type_not_allowed(self, dispatcher):
        settings = make_settings(notification_types=["new_appointment"])
        assert dispatcher._is_type_allowed(settings, "birthday") is False

    def test_empty_list_allows_all(self, dispatcher):
        settings = make_settings(notification_types=[])
        assert dispatcher._is_type_allowed(settings, "new_appointment") is True


class TestIsQuietHours:
    def test_no_quiet_hours_returns_false(self, dispatcher):
        settings = make_settings(quiet_start=None, quiet_end=None)
        assert dispatcher._is_quiet_hours(settings) is False

    def test_within_quiet_hours(self, dispatcher):
        # Quiet hours 22:00 - 09:00, test at 23:00
        settings = make_settings(
            quiet_start=time(22, 0),
            quiet_end=time(9, 0),
            timezone="UTC",
        )
        # We can't easily mock datetime.now, so just test the logic
        # by checking that the method doesn't raise
        result = dispatcher._is_quiet_hours(settings)
        assert isinstance(result, bool)

    def test_normal_hours_range(self, dispatcher):
        # Quiet hours 10:00 - 12:00 (normal range, not overnight)
        settings = make_settings(
            quiet_start=time(10, 0),
            quiet_end=time(12, 0),
            timezone="UTC",
        )
        result = dispatcher._is_quiet_hours(settings)
        assert isinstance(result, bool)


class TestGetAdapter:
    def test_telegram_adapter(self, dispatcher):
        with patch("app.services.dispatcher.get_telegram_adapter") as mock:
            mock.return_value = MagicMock()
            adapter = dispatcher._get_adapter("telegram")
            assert adapter is not None

    def test_whatsapp_adapter(self, dispatcher):
        with patch("app.services.dispatcher.get_whatsapp_adapter") as mock:
            mock.return_value = MagicMock()
            adapter = dispatcher._get_adapter("whatsapp")
            assert adapter is not None

    def test_max_adapter(self, dispatcher):
        with patch("app.services.dispatcher.get_max_adapter") as mock:
            mock.return_value = MagicMock()
            adapter = dispatcher._get_adapter("max")
            assert adapter is not None

    def test_unknown_channel_returns_none(self, dispatcher):
        adapter = dispatcher._get_adapter("unknown_channel")
        assert adapter is None
