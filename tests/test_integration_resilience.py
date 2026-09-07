from unittest.mock import AsyncMock

import httpx
import pytest

from app.integrations.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    IntegrationError,
    with_retry,
)


@pytest.mark.asyncio
async def test_retry_recovers_from_transient_failure() -> None:
    operation = AsyncMock(side_effect=[IntegrationError("temporary"), {"ok": True}])
    result = await with_retry(operation, attempts=2, base_delay=0)
    assert result == {"ok": True}
    assert operation.await_count == 2


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold() -> None:
    breaker = CircuitBreaker("provider", failure_threshold=2, recovery_timeout=60)
    operation = AsyncMock(side_effect=IntegrationError("down"))
    with pytest.raises(IntegrationError):
        await breaker.call(operation)
    with pytest.raises(IntegrationError):
        await breaker.call(operation)
    with pytest.raises(CircuitOpenError):
        await breaker.call(operation)
    assert operation.await_count == 2


@pytest.mark.asyncio
async def test_http_500_is_retried_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.resilience import ReliableHTTPClient

    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="temporary")
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("app.integrations.resilience.asyncio.sleep", AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ReliableHTTPClient("test-provider", max_retries=2, http=http)
        assert await client.request("GET", "https://provider.example/data") == {"ok": True}
    assert calls == 2
