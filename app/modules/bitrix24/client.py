from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.resilience import IntegrationError, ReliableHTTPClient, get_circuit_breaker


class BitrixError(IntegrationError):
    def __init__(self, code: str, description: str = "") -> None:
        self.code = code
        self.description = description
        super().__init__(f"{code}: {description}".rstrip(": "))


class Bitrix24Client:
    def __init__(
        self,
        webhook_url: str | None = None,
        *,
        settings: Settings | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.webhook_url = (webhook_url or self.settings.bitrix24_webhook_url).rstrip("/")
        self.transport = ReliableHTTPClient(
            "bitrix24",
            max_retries=self.settings.integration_max_retries,
            circuit_breaker=get_circuit_breaker(
                "bitrix24",
                self.settings.integration_circuit_failure_threshold,
                self.settings.integration_circuit_recovery_seconds,
            ),
            http=http,
        )

    async def _call(self, method: str, params: dict[str, object] | None = None) -> Any:
        if not self.webhook_url:
            raise BitrixError("not_configured", "BITRIX24_WEBHOOK_URL is empty")
        data = await self.transport.request(
            "POST", f"{self.webhook_url}/{method}.json", json=params or {}
        )
        if data.get("error"):
            raise BitrixError(str(data["error"]), str(data.get("error_description", "")))
        return data.get("result", data)

    async def test_connection(self) -> dict[str, object]:
        result = await self._call("profile")
        return dict(result) if isinstance(result, dict) else {"result": result}

    async def create_lead(self, fields: dict[str, object]) -> int:
        return int(await self._call("crm.lead.add", {"fields": fields}))

    async def update_lead(self, lead_id: int, fields: dict[str, object]) -> None:
        await self._call("crm.lead.update", {"id": lead_id, "fields": fields})

    async def get_lead(self, lead_id: int) -> dict[str, object] | None:
        result = await self._call("crm.lead.get", {"id": lead_id})
        return dict(result) if isinstance(result, dict) else None

    async def find_lead_by_email(self, email: str) -> dict[str, object] | None:
        duplicate = await self._call(
            "crm.duplicate.findbycomm", {"type": "EMAIL", "values": [email], "entity_type": "LEAD"}
        )
        ids: list[object] = []
        if isinstance(duplicate, dict):
            raw = duplicate.get("LEAD", [])
            if isinstance(raw, list):
                ids = raw
        return await self.get_lead(int(str(ids[0]))) if ids else None

    async def create_contact(self, fields: dict[str, object]) -> int:
        return int(await self._call("crm.contact.add", {"fields": fields}))

    async def create_company(self, fields: dict[str, object]) -> int:
        return int(await self._call("crm.company.add", {"fields": fields}))

    async def create_deal(self, fields: dict[str, object]) -> int:
        return int(await self._call("crm.deal.add", {"fields": fields}))

    async def create_email_activity(
        self,
        owner_id: int,
        owner_type: str,
        subject: str,
        description: str,
        direction: str,
        *,
        message_id: str | None = None,
    ) -> int:
        fields: dict[str, object] = {
            "OWNER_ID": owner_id,
            "OWNER_TYPE_ID": {"L": 1, "D": 2, "C": 3, "CO": 4}.get(owner_type.upper(), owner_type),
            "TYPE_ID": 4,
            "DIRECTION": 2 if direction == "O" else 1,
            "SUBJECT": subject,
            "DESCRIPTION": description,
            "DESCRIPTION_TYPE": 3,
            "COMPLETED": "Y",
        }
        if message_id:
            fields["ORIGIN_ID"] = message_id
        return int(await self._call("crm.activity.add", {"fields": fields}))

    async def list_activities(self, filters: dict[str, object]) -> list[dict[str, object]]:
        result = await self._call(
            "crm.activity.list",
            {
                "filter": filters,
                "select": [
                    "ID",
                    "OWNER_ID",
                    "OWNER_TYPE_ID",
                    "DIRECTION",
                    "SUBJECT",
                    "CREATED",
                    "ORIGIN_ID",
                ],
            },
        )
        return [dict(row) for row in result] if isinstance(result, list) else []

    async def create_lead_user_field(self, field: dict[str, object]) -> int:
        return int(await self._call("crm.lead.userfield.add", {"fields": field}))
