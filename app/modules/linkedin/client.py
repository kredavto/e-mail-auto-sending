from __future__ import annotations

import hashlib
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.resilience import (
    AsyncRateLimiter,
    IntegrationError,
    ReliableHTTPClient,
    get_circuit_breaker,
)


class LinkedInClient:
    def __init__(
        self,
        access_token: str | None = None,
        *,
        settings: Settings | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.access_token = access_token or self.settings.linkedin_access_token
        self.transport = ReliableHTTPClient(
            "linkedin",
            max_retries=self.settings.integration_max_retries,
            rate_limiter=AsyncRateLimiter(80, 60),
            circuit_breaker=get_circuit_breaker(
                "linkedin",
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
            raise IntegrationError("LINKEDIN_ACCESS_TOKEN is empty")
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "LinkedIn-Version": self.settings.linkedin_api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        return await self.transport.request(
            method,
            f"{self.settings.linkedin_api_base_url.rstrip('/')}/{path.lstrip('/')}",
            headers=headers,
            params=params,
            json=json,
        )

    async def get_lead_gen_forms(self, ad_account_id: str) -> list[dict[str, object]]:
        payload = await self._request(
            "GET",
            "leadForms",
            params={"q": "owner", "owner": f"urn:li:sponsoredAccount:{ad_account_id}"},
        )
        rows = payload.get("elements", [])
        return [dict(row) for row in rows] if isinstance(rows, list) else []

    async def get_form_leads(self, form_id: str) -> list[dict[str, object]]:
        payload = await self._request(
            "GET", "leadFormResponses", params={"q": "leadForm", "leadForm": form_id}
        )
        rows = payload.get("elements", [])
        return [dict(row) for row in rows] if isinstance(rows, list) else []

    async def create_matched_audience(self, name: str, emails: list[str]) -> str:
        segment = await self._request(
            "POST",
            "dmpSegments",
            json={"name": name, "type": "USER", "sourcePlatform": "LIST_UPLOAD"},
        )
        segment_id = str(segment.get("id") or segment.get("value") or "")
        if not segment_id:
            raise IntegrationError("LinkedIn did not return a matched audience id")
        hashed = [hashlib.sha256(email.strip().casefold().encode()).hexdigest() for email in emails]
        await self._request(
            "POST",
            f"dmpSegments/{segment_id}/users",
            json={"elements": [{"userIds": [value]} for value in hashed]},
        )
        return segment_id
