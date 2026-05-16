"""
tests/unit/test_security.py — Unit tests for security utilities.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.utils.security import hash_phone, mask_phone, validate_webhook_signature


class TestHashPhone:
    def test_same_phone_same_hash(self):
        assert hash_phone("+79001234567") == hash_phone("+79001234567")

    def test_different_phones_different_hashes(self):
        assert hash_phone("+79001234567") != hash_phone("+79007654321")

    def test_returns_hex_string(self):
        result = hash_phone("+79001234567")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_normalises_phone(self):
        # With and without spaces should produce same hash
        h1 = hash_phone("+7 900 123-45-67")
        h2 = hash_phone("+79001234567")
        assert h1 == h2


class TestMaskPhone:
    def test_masks_middle_digits(self):
        result = mask_phone("+79001234567")
        assert "***" in result
        assert result.startswith("+790")
        assert result.endswith("4567")

    def test_short_phone_returned_as_is(self):
        result = mask_phone("123")
        assert result == "123"


class TestValidateWebhookSignature:
    def _make_signature(self, payload: bytes, secret: str) -> str:
        digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature_returns_true(self):
        payload = b'{"test": "data"}'
        secret = "my_secret"
        sig = self._make_signature(payload, secret)
        assert validate_webhook_signature(payload, sig, secret) is True

    def test_invalid_signature_returns_false(self):
        payload = b'{"test": "data"}'
        assert validate_webhook_signature(payload, "sha256=invalid", "secret") is False

    def test_wrong_format_returns_false(self):
        payload = b'{"test": "data"}'
        assert validate_webhook_signature(payload, "md5=abc123", "secret") is False

    def test_tampered_payload_returns_false(self):
        payload = b'{"test": "data"}'
        secret = "my_secret"
        sig = self._make_signature(payload, secret)
        tampered = b'{"test": "tampered"}'
        assert validate_webhook_signature(tampered, sig, secret) is False
