"""
tests/property/test_properties.py — Property-based tests using Hypothesis.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st
from unittest.mock import MagicMock

from app.services.template_engine import TemplateEngine, ALLOWED_VARIABLES
from app.utils.security import hash_phone, mask_phone, validate_webhook_signature


# ── Property 1: Template rendering never raises ───────────────────────────────

@given(
    context=st.fixed_dictionaries(
        {var: st.text(max_size=50) for var in ALLOWED_VARIABLES}
    )
)
@settings(max_examples=100)
def test_template_render_never_raises(context):
    """
    Property: rendering any template with any string values never raises an exception.
    """
    mock_db = MagicMock()
    mock_redis = None
    engine = TemplateEngine(db=mock_db, redis=mock_redis)

    template = (
        "Привет, {{client_name}}! "
        "Запись {{appointment_date}} в {{appointment_time}}. "
        "Мастер: {{master_name}}. Услуга: {{service_name}}. "
        "Адрес: {{salon_address}}. Тел: {{salon_phone}}. {{salon_name}}"
    )

    # Should never raise
    result = engine.render_body(template, context)
    assert isinstance(result, str)


# ── Property 2: Phone hashing is deterministic ────────────────────────────────

@given(phone=st.text(alphabet="+0123456789", min_size=7, max_size=15))
@settings(max_examples=100)
def test_phone_hash_deterministic(phone):
    """
    Property: hashing the same phone number always produces the same result.
    """
    h1 = hash_phone(phone)
    h2 = hash_phone(phone)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


# ── Property 3: Different phones produce different hashes ─────────────────────

@given(
    phone1=st.text(alphabet="0123456789", min_size=10, max_size=11),
    phone2=st.text(alphabet="0123456789", min_size=10, max_size=11),
)
@settings(max_examples=50)
def test_different_phones_different_hashes(phone1, phone2):
    """
    Property: two different phone numbers (almost always) produce different hashes.
    """
    if phone1 != phone2:
        assert hash_phone(phone1) != hash_phone(phone2)


# ── Property 4: Template validation never raises ──────────────────────────────

@given(template_body=st.text(max_size=500))
@settings(max_examples=100)
def test_template_validation_never_raises(template_body):
    """
    Property: validate_template never raises an exception for any input.
    """
    mock_db = MagicMock()
    engine = TemplateEngine(db=mock_db, redis=None)

    # Should never raise
    result = engine.validate_template(template_body)
    assert isinstance(result, list)


# ── Property 5: Webhook signature validation is consistent ───────────────────

@given(
    payload=st.binary(min_size=1, max_size=1000),
    secret=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))),
)
@settings(max_examples=50)
def test_webhook_signature_consistent(payload, secret):
    """
    Property: a correctly computed signature always validates successfully.
    """
    import hashlib
    import hmac as hmac_module

    digest = hmac_module.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    signature = f"sha256={digest}"

    assert validate_webhook_signature(payload, signature, secret) is True


# ── Property 6: Mask phone always contains *** ────────────────────────────────

@given(phone=st.text(alphabet="+0123456789", min_size=8, max_size=15))
@settings(max_examples=50)
def test_mask_phone_contains_stars(phone):
    """
    Property: masking a phone number of sufficient length always produces ***.
    """
    result = mask_phone(phone)
    if len(phone) >= 7:
        assert "***" in result
