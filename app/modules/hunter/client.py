from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.resilience import (
    AsyncRateLimiter,
    IntegrationError,
    ReliableHTTPClient,
    get_circuit_breaker,
)


class HunterClient:
    BASE_URL = "https://api.hunter.io/v2"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        settings: Settings | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.api_key = api_key or self.settings.hunter_api_key
        self.transport = ReliableHTTPClient(
            "hunter",
            max_retries=self.settings.integration_max_retries,
            rate_limiter=AsyncRateLimiter(10, 1),
            circuit_breaker=get_circuit_breaker(
                "hunter",
                self.settings.integration_circuit_failure_threshold,
                self.settings.integration_circuit_recovery_seconds,
            ),
            http=http,
        )

    async def _get(self, path: str, params: dict[str, object] | None = None) -> Any:
        if not self.api_key:
            raise IntegrationError("HUNTER_API_KEY is empty")
        query = dict(params or {})
        query["api_key"] = self.api_key
        payload = await self.transport.request("GET", f"{self.BASE_URL}/{path}", params=query)
        if payload.get("errors"):
            raise IntegrationError(f"Hunter API error: {payload['errors']}")
        return payload.get("data")

    async def find_email(
        self, domain: str, first_name: str, last_name: str
    ) -> dict[str, object] | None:
        data = await self._get(
            "email-finder",
            {"domain": domain, "first_name": first_name, "last_name": last_name},
        )
        if isinstance(data, dict) and data.get("email"):
            return {
                "email": str(data["email"]).casefold(),
                "confidence": int(data.get("score", 0)),
                "position": data.get("position"),
            }
        return None

    async def verify_email(self, email: str) -> dict[str, object]:
        data = await self._get("email-verifier", {"email": email})
        return dict(data) if isinstance(data, dict) else {}

    async def domain_search(self, domain: str) -> list[dict[str, object]]:
        data = await self._get("domain-search", {"domain": domain})
        emails = data.get("emails", []) if isinstance(data, dict) else []
        return [dict(row) for row in emails] if isinstance(emails, list) else []

    async def account_info(self) -> dict[str, object]:
        data = await self._get("account")
        return dict(data) if isinstance(data, dict) else {}
