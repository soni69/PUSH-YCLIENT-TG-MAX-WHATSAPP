"""
tests/integration/test_webhook.py — Integration tests for webhook endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    with patch("app.main._check_required_env_vars"):
        with patch("app.main.lifespan"):
            from app.main import app
            return TestClient(app, raise_server_exceptions=False)


def make_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class TestYClientsWebhook:
    def test_valid_webhook_returns_accepted(self, client):
        payload = {"resource": "record", "resource_id": 123, "status": "create", "company_id": 1}
        body = json.dumps(payload).encode()
        sig = make_signature(body, "test_secret")

        with patch("app.api.webhook._queue_yclients_event", new_callable=AsyncMock):
            response = client.post(
                "/webhook/yclients",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Yclients-Signature": sig,
                },
            )
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

    def test_invalid_signature_returns_401(self, client):
        payload = {"resource": "record", "resource_id": 123, "status": "create"}
        body = json.dumps(payload).encode()

        response = client.post(
            "/webhook/yclients",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Yclients-Signature": "sha256=invalidsignature",
            },
        )
        assert response.status_code == 401

    def test_invalid_json_returns_400(self, client):
        response = client.post(
            "/webhook/yclients",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in (400, 422)


class TestHealthEndpoint:
    def test_health_endpoint_exists(self, client):
        with patch("app.api.health._check_postgres", new_callable=AsyncMock) as mock_pg:
            with patch("app.api.health._check_redis", new_callable=AsyncMock) as mock_redis:
                with patch("app.api.health._check_yclients", new_callable=AsyncMock) as mock_yc:
                    with patch("app.api.health._check_telegram", new_callable=AsyncMock) as mock_tg:
                        mock_pg.return_value = {"status": "ok", "latency_ms": 1.0}
                        mock_redis.return_value = {"status": "ok", "latency_ms": 0.5}
                        mock_yc.return_value = {"status": "ok", "latency_ms": 100.0}
                        mock_tg.return_value = {"status": "ok", "latency_ms": 50.0}

                        response = client.get("/health")
                        assert response.status_code == 200
                        data = response.json()
                        assert "status" in data
                        assert "services" in data
