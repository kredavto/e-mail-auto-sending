from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from app.core.exceptions import AppError

logger = logging.getLogger("app.integrations")


class IntegrationError(AppError):
    """A normalized failure returned by an external provider."""

    status_code = 502
    code = "integration_error"


class CircuitOpenError(IntegrationError):
    status_code = 503
    code = "integration_circuit_open"


class IntegrationRequestError(AppError):
    """A permanent provider rejection that must not be retried."""

    status_code = 502
    code = "integration_request_rejected"


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    failures: int = 0
    opened_at: float | None = None

    async def call[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        now = monotonic()
        if self.opened_at is not None:
            if now - self.opened_at < self.recovery_timeout:
                raise CircuitOpenError(f"Circuit {self.name} is open")
            self.opened_at = None
        try:
            result = await operation()
        except Exception:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.opened_at = monotonic()
            raise
        self.failures = 0
        self.opened_at = None
        return result


_CIRCUITS: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str, failure_threshold: int = 5, recovery_timeout: float = 60.0
) -> CircuitBreaker:
    """Return the process-wide circuit for a provider, shared by client instances."""
    circuit = _CIRCUITS.get(name)
    if circuit is None:
        circuit = CircuitBreaker(name, failure_threshold, recovery_timeout)
        _CIRCUITS[name] = circuit
    return circuit


class AsyncRateLimiter:
    """Process-local spacing limiter; provider quotas still remain the source of truth."""

    def __init__(self, requests: int, period_seconds: float) -> None:
        self.interval = period_seconds / requests
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = monotonic()
            delay = max(0.0, self._next_at - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_at = max(now, self._next_at) + self.interval


class FixedWindowRateLimiter:
    """Allows provider-sized bursts while enforcing a rolling process-local quota."""

    def __init__(self, requests: int, period_seconds: float) -> None:
        self.requests = requests
        self.period_seconds = period_seconds
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = monotonic()
            while self._calls and self._calls[0] <= now - self.period_seconds:
                self._calls.popleft()
            if len(self._calls) >= self.requests:
                delay = self.period_seconds - (now - self._calls[0])
                await asyncio.sleep(max(0, delay))
                now = monotonic()
                while self._calls and self._calls[0] <= now - self.period_seconds:
                    self._calls.popleft()
            self._calls.append(now)


class RateLimiter(Protocol):
    async def acquire(self) -> None: ...


async def with_retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.25,
    retry_for: tuple[type[BaseException], ...] = (
        httpx.TimeoutException,
        httpx.NetworkError,
        IntegrationError,
    ),
) -> T:
    for attempt in range(attempts):
        try:
            return await operation()
        except retry_for:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(base_delay * (2**attempt) + random.uniform(0, base_delay))
    raise AssertionError("unreachable")


class ReliableHTTPClient:
    def __init__(
        self,
        provider: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        rate_limiter: RateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider = provider
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limiter = rate_limiter
        self.circuit_breaker = circuit_breaker
        self.http = http

    async def request(self, method: str, url: str, **kwargs: Any) -> dict[str, object]:
        async def operation() -> dict[str, object]:
            if self.rate_limiter:
                await self.rate_limiter.acquire()
            started = monotonic()
            safe_url = self._safe_url(url)
            logger.info(
                "external_request provider=%s method=%s url=%s", self.provider, method, safe_url
            )
            try:
                if self.http:
                    response = await self.http.request(method, url, timeout=self.timeout, **kwargs)
                else:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise IntegrationError(f"{self.provider} returned a non-object response")
                return payload
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                logger.warning(
                    "external_response provider=%s status=%s duration_ms=%d",
                    self.provider,
                    status,
                    int((monotonic() - started) * 1000),
                )
                if status == 429 or status >= 500:
                    raise IntegrationError(f"{self.provider} temporary HTTP {status}") from exc
                raise IntegrationRequestError(
                    f"{self.provider} rejected the request with HTTP {status}"
                ) from None
            finally:
                logger.info(
                    "external_request_done provider=%s duration_ms=%d",
                    self.provider,
                    int((monotonic() - started) * 1000),
                )

        async def retried() -> dict[str, object]:
            return await with_retry(operation, attempts=self.max_retries)

        if self.circuit_breaker:
            return await self.circuit_breaker.call(retried)
        return await retried()

    def _safe_url(self, url: str) -> str:
        parsed = urlsplit(url)
        path = parsed.path
        if self.provider == "bitrix24":
            path = f"/{path.rsplit('/', 1)[-1]}"
        return f"{parsed.scheme}://{parsed.netloc}{path}"
