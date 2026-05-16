"""
app/utils/rate_limiter.py — Token bucket rate limiter for messenger APIs.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class TokenBucket:
    """
    Async token bucket rate limiter.

    Allows up to `rate` tokens per `per` seconds.
    Tokens are consumed one at a time; if the bucket is empty, the caller waits.
    """

    def __init__(self, rate: float, per: float = 1.0) -> None:
        self._rate = rate        # tokens per `per` seconds
        self._per = per          # time window in seconds
        self._tokens = rate      # current token count
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            # Refill tokens based on elapsed time
            self._tokens = min(
                self._rate,
                self._tokens + elapsed * (self._rate / self._per),
            )
            self._last_refill = now

            if self._tokens < 1:
                wait = (1 - self._tokens) * (self._per / self._rate)
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


class TelegramRateLimiter:
    """
    Enforces Telegram Bot API rate limits:
    - Global: 30 messages/second across all chats
    - Per-chat: 1 message/second per chat_id
    """

    def __init__(self) -> None:
        # Global bucket: 30 messages/second
        self._global_bucket = TokenBucket(rate=30, per=1.0)
        # Per-chat buckets: 1 message/second
        self._chat_buckets: dict[int, TokenBucket] = defaultdict(
            lambda: TokenBucket(rate=1, per=1.0)
        )

    async def acquire(self, chat_id: int) -> None:
        """Acquire tokens from both global and per-chat buckets."""
        await self._global_bucket.acquire()
        await self._chat_buckets[chat_id].acquire()


# Module-level singletons
_telegram_limiter: TelegramRateLimiter | None = None


def get_telegram_rate_limiter() -> TelegramRateLimiter:
    global _telegram_limiter
    if _telegram_limiter is None:
        _telegram_limiter = TelegramRateLimiter()
    return _telegram_limiter
