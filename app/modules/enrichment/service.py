from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.integrations.resilience import IntegrationError
from app.modules.contacts.models import Contact
from app.modules.email_validation.service import EmailValidationService, ValidationData
from app.modules.enrichment.models import EnrichmentResult
from app.modules.hunter.service import HunterService
from app.modules.linkedin.models import LinkedInProfile
from app.modules.tenchat.models import TenchatProfile


@dataclass
class Candidate:
    email: str
    source: str
    confidence: int
    data: dict[str, object]


class EnrichmentOrchestrator:
    MIN_CONFIDENCE = 70

    def __init__(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        hunter: HunterService | None = None,
        validator: EmailValidationService | None = None,
    ) -> None:
        self.db, self.workspace_id = db, workspace_id
        self.hunter = hunter or HunterService()
        self.validator = validator or EmailValidationService(resolver=None, providers=[])

    @staticmethod
    def extract_domain(contact: Contact) -> str | None:
        candidates = [
            contact.current_site_url,
            str(contact.custom_fields.get("website", "")),
            contact.company,
        ]
        for raw in candidates:
            if not raw:
                continue
            value = str(raw).strip().casefold()
            parsed = urlparse(value if "://" in value else f"//{value}")
            host = (parsed.hostname or "").removeprefix("www.").rstrip(".")
            if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}\.)+[a-z]{2,63}", host):
                return host
        return None

    @staticmethod
    def _name(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.casefold())

    async def _patterns(self, contact: Contact, domain: str) -> list[Candidate]:
        first, last = self._name(contact.first_name), self._name(contact.last_name)
        if not first or not last:
            return []
        addresses = [f"{first}.{last}@{domain}", f"{first[0]}{last}@{domain}", f"{first}@{domain}"]
        results: list[Candidate] = []
        for email in addresses:
            validation = await self.validator.validate(email, smtp_check=True, persist=False)
            assert isinstance(validation, ValidationData)
            if validation.smtp_check_passed and validation.score >= self.MIN_CONFIDENCE:
                results.append(
                    Candidate(
                        email,
                        "company_pattern",
                        validation.score,
                        {"pattern": email.split("@", 1)[0]},
                    )
                )
        return results

    async def enrich_contact(self, contact: Contact) -> EnrichmentResult:
        if contact.workspace_id != self.workspace_id:
            raise NotFoundError("Контакт не найден")
        domain = self.extract_domain(contact)
        candidates: list[Candidate] = []
        linkedin = await self.db.scalar(
            select(LinkedInProfile).where(
                LinkedInProfile.workspace_id == self.workspace_id,
                LinkedInProfile.contact_id == contact.id,
            )
        )
        if linkedin and linkedin.email and (linkedin.email_confidence or 0) >= self.MIN_CONFIDENCE:
            candidates.append(
                Candidate(
                    linkedin.email,
                    "linkedin",
                    linkedin.email_confidence or 0,
                    {"profile_url": linkedin.profile_url},
                )
            )
        tenchat = await self.db.scalar(
            select(TenchatProfile).where(
                TenchatProfile.workspace_id == self.workspace_id,
                TenchatProfile.contact_id == contact.id,
            )
        )
        if tenchat and tenchat.email:
            validation = await self.validator.validate(tenchat.email, persist=False)
            assert isinstance(validation, ValidationData)
            if validation.score >= self.MIN_CONFIDENCE:
                candidates.append(
                    Candidate(
                        tenchat.email,
                        "tenchat",
                        min(validation.score, 85),
                        {"tenchat_user_id": tenchat.tenchat_user_id},
                    )
                )
        if domain and contact.first_name and contact.last_name:
            try:
                hunter = await self.hunter.find_confident_email(
                    domain, contact.first_name, contact.last_name
                )
            except (IntegrationError, OSError, TimeoutError):
                hunter = None
            if hunter:
                candidates.append(
                    Candidate(
                        str(hunter["email"]),
                        "hunter",
                        int(str(hunter["confidence"])),
                        dict(hunter),
                    )
                )
            candidates.extend(await self._patterns(contact, domain))
        best = max(candidates, key=lambda item: item.confidence) if candidates else None
        row = EnrichmentResult(
            workspace_id=self.workspace_id,
            contact_id=contact.id,
            email=best.email if best and best.confidence >= self.MIN_CONFIDENCE else None,
            source=best.source if best and best.confidence >= self.MIN_CONFIDENCE else None,
            confidence=best.confidence if best else 0,
            enriched_data={"domain": domain, **(best.data if best else {})},
        )
        self.db.add(row)
        if row.email and (not contact.email or contact.email.endswith("@placeholder.invalid")):
            contact.email = row.email
            contact.source = row.source or contact.source
        await self.db.flush()
        return row

    async def enrich(self, contact_id: UUID) -> EnrichmentResult:
        contact = await self.db.get(Contact, contact_id)
        if not contact or contact.workspace_id != self.workspace_id:
            raise NotFoundError("Контакт не найден")
        return await self.enrich_contact(contact)

    async def stats(self) -> dict[str, object]:
        rows = list(
            (
                await self.db.scalars(
                    select(EnrichmentResult).where(
                        EnrichmentResult.workspace_id == self.workspace_id
                    )
                )
            ).all()
        )
        found = [row for row in rows if row.email and row.confidence >= self.MIN_CONFIDENCE]
        return {
            "total": len(rows),
            "enriched": len(found),
            "success_rate": len(found) / len(rows) if rows else 0,
            "average_confidence": sum(row.confidence for row in found) / len(found) if found else 0,
        }

    @staticmethod
    def sources() -> list[dict[str, object]]:
        return [
            {"name": "hunter", "enabled": True, "minimum_confidence": 70},
            {"name": "company_pattern", "enabled": True, "minimum_confidence": 70},
            {"name": "linkedin", "enabled": True, "minimum_confidence": 70},
            {"name": "tenchat", "enabled": True, "minimum_confidence": 70},
        ]
