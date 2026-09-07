from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.resilience import (
    FixedWindowRateLimiter,
    IntegrationError,
    ReliableHTTPClient,
    get_circuit_breaker,
)


class TenchatClient:
    BASE_URL = "https://api.tenchat.ru/v1"

    def __init__(
        self,
        access_token: str | None = None,
        *,
        settings: Settings | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.access_token = access_token or self.settings.tenchat_access_token
        self.base_url = self.settings.tenchat_api_base_url.rstrip("/")
        self.transport = ReliableHTTPClient(
            "tenchat",
            max_retries=self.settings.integration_max_retries,
            rate_limiter=FixedWindowRateLimiter(100, 3600),
            circuit_breaker=get_circuit_breaker(
                "tenchat",
                self.settings.integration_circuit_failure_threshold,
                self.settings.integration_circuit_recovery_seconds,
            ),
            http=http,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json: object = None,
    ) -> dict[str, Any]:
        if not self.access_token:
            raise IntegrationError("TENCHAT_ACCESS_TOKEN is empty")
        return await self.transport.request(
            method,
            f"{self.base_url}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            params=params,
            json=json,
        )

    async def search_users(
        self,
        industry: str | None = None,
        city: str | None = None,
        position: str | None = None,
        per_page: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, object] = {"per_page": min(per_page, 50)}
        params.update(
            {
                k: v
                for k, v in {"industry": industry, "city": city, "position": position}.items()
                if v
            }
        )
        return await self._request("GET", "users/search", params=params)

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        return await self._request("GET", f"users/{user_id}")

    async def send_message(self, user_id: str, text: str) -> dict[str, Any]:
        return await self._request("POST", "messages", json={"recipient_id": user_id, "text": text})

    async def get_conversations(self, per_page: int = 50) -> dict[str, Any]:
        return await self._request("GET", "conversations", params={"per_page": min(per_page, 50)})

    async def get_messages(self, conversation_id: str) -> dict[str, Any]:
        return await self._request("GET", f"conversations/{conversation_id}/messages")

    async def follow_user(self, user_id: str) -> dict[str, Any]:
        return await self._request("POST", f"users/{user_id}/follow")

    async def enrich_profile(self, user_id: str) -> dict[str, Any]:
        return await self.get_user_profile(user_id)
