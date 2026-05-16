"""
app/utils/security.py — HMAC validation, phone hashing, JWT utilities.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def hash_phone(phone: str) -> str:
    """
    Return SHA-256 hex digest of a normalised phone number.
    Used for lookup without storing the raw number.
    """
    # Normalise: keep only digits and leading +
    normalised = "".join(c for c in phone if c.isdigit() or c == "+")
    return hashlib.sha256(normalised.encode()).hexdigest()


def mask_phone(phone: str) -> str:
    """
    Return a masked version of the phone number for storage.
    Example: +79001234567 → +7900***4567
    """
    digits_only = "".join(c for c in phone if c.isdigit())
    if len(digits_only) < 7:
        return phone
    return phone[:4] + "***" + phone[-4:]


def validate_webhook_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """
    Validate HMAC-SHA256 signature from YClients webhook.

    Expected header format: sha256={hex_digest}
    """
    if not signature_header.startswith("sha256="):
        logger.warning("webhook_invalid_signature_format", header=signature_header[:20])
        return False

    provided_digest = signature_header[len("sha256="):]
    expected_digest = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    is_valid = hmac.compare_digest(expected_digest, provided_digest)
    if not is_valid:
        logger.warning("webhook_signature_mismatch")
    return is_valid


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token for AdminPanel."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.admin_jwt_expire_minutes)
    )
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.admin_jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> str | None:
    """
    Decode and validate a JWT access token.
    Returns the subject (username) or None if invalid/expired.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.admin_jwt_secret, algorithms=["HS256"])
        return payload.get("sub")
    except JWTError:
        return None
