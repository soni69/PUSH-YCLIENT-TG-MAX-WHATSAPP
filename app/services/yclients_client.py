"""
app/services/yclients_client.py — YClients API client with retry and circuit breaker.
"""

from __future__ import annotations

import asyncio
import time as time_module
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.schemas.yclients import (
    AppointmentData,
    ClientInfo,
    YClientsAppointmentListResponse,
    YClientsClientResponse,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

# YClients appointment status IDs
YCLIENTS_STATUS_CONFIRMED = 1
YCLIENTS_STATUS_CANCELLED = 2
YCLIENTS_STATUS_IN_PROGRESS = 3
YCLIENTS_STATUS_WAITING = 0
YCLIENTS_STATUS_COMPLETED = 7


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open (API is unavailable)."""


class YClientsAPIError(Exception):
    """Raised on non-retryable YClients API errors."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"YClients API error {status_code}: {message}")


class YClientsClient:
    """
    Async HTTP client for YClients API v1.

    Features:
    - Bearer token authentication
    - Exponential backoff on HTTP 429 (start 1s, max 60s)
    - Circuit breaker: pause 5 minutes after 3 consecutive 5xx errors
    - Token never logged
    """

    BASE_URL = "https://api.yclients.com/api/v1"

    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.yclients_api_token
        self._company_id = settings.yclients_company_id
        self._client: httpx.AsyncClient | None = None

        # Circuit breaker state
        self._consecutive_5xx = 0
        self._circuit_open_until: float = 0.0  # epoch seconds

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.yclients.v2+json",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute an HTTP request with retry logic.

        - HTTP 429: exponential backoff (1s → 2s → 4s … max 60s)
        - HTTP 5xx × 3: open circuit breaker for 5 minutes
        """
        # Check circuit breaker
        if time_module.monotonic() < self._circuit_open_until:
            remaining = self._circuit_open_until - time_module.monotonic()
            logger.warning(
                "circuit_breaker_open",
                endpoint=endpoint,
                retry_in_seconds=round(remaining),
            )
            raise CircuitBreakerOpen(
                f"YClients API circuit breaker open for {remaining:.0f}s more"
            )

        client = await self._get_client()
        backoff = 1.0
        max_backoff = 60.0

        for attempt in range(1, 6):  # max 5 attempts for rate limiting
            try:
                response = await client.request(method, endpoint, **kwargs)
            except httpx.RequestError as exc:
                logger.error(
                    "yclients_request_error",
                    endpoint=endpoint,
                    error=str(exc),
                )
                raise

            if response.status_code == 429:
                retry_after = float(
                    response.headers.get("Retry-After", backoff)
                )
                wait = min(retry_after, max_backoff)
                logger.warning(
                    "yclients_rate_limited",
                    endpoint=endpoint,
                    wait_seconds=wait,
                    attempt=attempt,
                )
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, max_backoff)
                continue

            if response.status_code >= 500:
                self._consecutive_5xx += 1
                logger.error(
                    "yclients_5xx_error",
                    endpoint=endpoint,
                    status_code=response.status_code,
                    consecutive=self._consecutive_5xx,
                )
                if self._consecutive_5xx >= 3:
                    self._circuit_open_until = time_module.monotonic() + 300  # 5 min
                    logger.error(
                        "circuit_breaker_opened",
                        endpoint=endpoint,
                        pause_seconds=300,
                    )
                    raise CircuitBreakerOpen("Circuit breaker opened after 3 consecutive 5xx")
                raise YClientsAPIError(response.status_code, response.text)

            # Successful response — reset circuit breaker counter
            self._consecutive_5xx = 0

            if response.status_code >= 400:
                raise YClientsAPIError(response.status_code, response.text)

            return response.json()

        raise YClientsAPIError(429, "Max retry attempts exceeded due to rate limiting")

    async def get_appointments(
        self,
        start_date: datetime,
        end_date: datetime,
        page: int = 1,
        count: int = 100,
    ) -> list[AppointmentData]:
        """Fetch appointments modified within the given time range."""
        params = {
            "start_date": start_date.strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": end_date.strftime("%Y-%m-%d %H:%M:%S"),
            "page": page,
            "count": count,
        }
        try:
            data = await self._request(
                "GET",
                f"/records/{self._company_id}",
                params=params,
            )
            appointments = []
            for item in data.get("data", []):
                try:
                    appt = AppointmentData(**item)
                    # Parse datetime string
                    if appt.datetime:
                        try:
                            appt.appointment_datetime = datetime.fromisoformat(
                                appt.datetime.replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass
                    appointments.append(appt)
                except Exception as exc:
                    logger.warning(
                        "appointment_parse_error",
                        error=str(exc),
                        item_id=item.get("id"),
                    )
            return appointments
        except (CircuitBreakerOpen, YClientsAPIError):
            raise
        except Exception as exc:
            logger.error("get_appointments_error", error=str(exc))
            return []

    async def get_appointment(self, appointment_id: int) -> AppointmentData | None:
        """Fetch a single appointment by ID."""
        try:
            data = await self._request(
                "GET",
                f"/record/{self._company_id}/{appointment_id}",
            )
            item = data.get("data", {})
            if not item:
                return None
            appt = AppointmentData(**item)
            if appt.datetime:
                try:
                    appt.appointment_datetime = datetime.fromisoformat(
                        appt.datetime.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass
            return appt
        except YClientsAPIError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def update_appointment_status(
        self,
        appointment_id: int,
        status_id: int,
        comment: str | None = None,
    ) -> bool:
        """Update appointment status. Returns True on success."""
        payload: dict[str, Any] = {"status_id": status_id}
        if comment:
            payload["comment"] = comment
        try:
            await self._request(
                "PUT",
                f"/record/{self._company_id}/{appointment_id}",
                json=payload,
            )
            logger.info(
                "appointment_status_updated",
                appointment_id=appointment_id,
                status_id=status_id,
            )
            return True
        except YClientsAPIError as exc:
            logger.error(
                "appointment_status_update_failed",
                appointment_id=appointment_id,
                status_code=exc.status_code,
                error=str(exc),
            )
            return False

    async def get_client(self, client_id: int) -> ClientInfo | None:
        """Fetch client data by YClients client ID."""
        try:
            data = await self._request(
                "GET",
                f"/client/{self._company_id}/{client_id}",
            )
            client_data = data.get("data")
            if not client_data:
                return None
            return ClientInfo(**client_data)
        except YClientsAPIError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def find_client_by_phone(self, phone: str) -> ClientInfo | None:
        """Search for a client by phone number."""
        try:
            data = await self._request(
                "GET",
                f"/clients/{self._company_id}",
                params={"phone": phone, "count": 1},
            )
            clients = data.get("data", [])
            if not clients:
                return None
            return ClientInfo(**clients[0])
        except YClientsAPIError:
            return None

    async def get_clients_with_birthdays(self, target_date: date) -> list[ClientInfo]:
        """Fetch clients whose birthday falls on the given date."""
        try:
            data = await self._request(
                "GET",
                f"/clients/{self._company_id}",
                params={
                    "birth_date": target_date.strftime("%Y-%m-%d"),
                    "count": 200,
                },
            )
            clients = []
            for item in data.get("data", []):
                try:
                    clients.append(ClientInfo(**item))
                except Exception:
                    pass
            return clients
        except (CircuitBreakerOpen, YClientsAPIError):
            return []


# Module-level singleton
_yclients_client: YClientsClient | None = None


def get_yclients_client() -> YClientsClient:
    global _yclients_client
    if _yclients_client is None:
        _yclients_client = YClientsClient()
    return _yclients_client
