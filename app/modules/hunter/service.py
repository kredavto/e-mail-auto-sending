from __future__ import annotations

from app.modules.hunter.client import HunterClient


class HunterService:
    MIN_CONFIDENCE = 70

    def __init__(self, client: HunterClient | None = None) -> None:
        self.client = client or HunterClient()

    async def find_confident_email(
        self, domain: str, first_name: str, last_name: str
    ) -> dict[str, object] | None:
        result = await self.client.find_email(domain, first_name, last_name)
        if not result or int(str(result.get("confidence", 0))) < self.MIN_CONFIDENCE:
            return None
        return result

    async def verify(self, email: str) -> dict[str, object]:
        result = await self.client.verify_email(email)
        score = int(str(result.get("score", 0)))
        status = str(result.get("status", "unknown"))
        return {**result, "accepted": score >= self.MIN_CONFIDENCE and status != "invalid"}
