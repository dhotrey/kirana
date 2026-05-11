from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol


class BoundLogger(Protocol):
    def debug(self, message: str) -> None: ...


class GeminiRateLimiter:
    def __init__(
        self,
        min_interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        async_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if min_interval_seconds <= 0:
            raise ValueError("min_interval_seconds must be > 0")
        self.min_interval_seconds = min_interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._async_sleep = async_sleep
        self._async_lock = asyncio.Lock()
        self._last_request_at: float | None = None

    def wait(self, log: BoundLogger | None = None) -> None:
        now = self._clock()
        if self._last_request_at is None:
            self._last_request_at = now
            if log is not None:
                log.debug("rate limiter first request: no sleep")
            return

        elapsed = now - self._last_request_at
        if elapsed < self.min_interval_seconds:
            sleep_for = self.min_interval_seconds - elapsed
            if log is not None:
                log.debug(
                    f"rate-limit sleep {sleep_for:.2f}s "
                    f"(interval={self.min_interval_seconds:.2f}s)"
                )
            self._sleep(sleep_for)
            now = self._clock()

        self._last_request_at = now

    async def wait_async(self, log: BoundLogger | None = None) -> None:
        async with self._async_lock:
            now = self._clock()
            if self._last_request_at is None:
                self._last_request_at = now
                if log is not None:
                    log.debug("rate limiter first request: no sleep")
                return

            elapsed = now - self._last_request_at
            if elapsed < self.min_interval_seconds:
                sleep_for = self.min_interval_seconds - elapsed
                if log is not None:
                    log.debug(
                        f"rate-limit sleep {sleep_for:.2f}s "
                        f"(interval={self.min_interval_seconds:.2f}s)"
                    )
                await self._async_sleep(sleep_for)
                now = self._clock()

            self._last_request_at = now


def retry_backoff_seconds(
    attempt: int,
    *,
    strategy: str,
    base_seconds: float,
    max_seconds: float,
) -> float:
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    if strategy == "constant":
        value = base_seconds
    elif strategy == "linear":
        value = base_seconds * attempt
    elif strategy == "exponential":
        value = base_seconds * (2 ** (attempt - 1))
    else:
        raise ValueError(f"Unsupported retry backoff strategy: {strategy}")
    return min(value, max_seconds)
