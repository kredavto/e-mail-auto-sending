from __future__ import annotations

from uuid import UUID

import dns.asyncresolver
import dns.exception
import dns.resolver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.audit import audited
from app.modules.domains.models import DomainVerification, SendingDomain
from app.modules.domains.schemas import DomainCreate


class DomainService:
    def __init__(
        self, db: AsyncSession, workspace_id: UUID, *, resolver: object | None = None
    ) -> None:
        self.db, self.workspace_id = db, workspace_id
        self.resolver = resolver or dns.asyncresolver.Resolver()

    async def list_all(self) -> list[SendingDomain]:
        return list(
            (
                await self.db.scalars(
                    select(SendingDomain)
                    .where(SendingDomain.workspace_id == self.workspace_id)
                    .order_by(SendingDomain.domain)
                )
            ).all()
        )

    async def get(self, domain_id: UUID) -> SendingDomain:
        row = await self.db.scalar(
            select(SendingDomain).where(
                SendingDomain.id == domain_id, SendingDomain.workspace_id == self.workspace_id
            )
        )
        if not row:
            raise NotFoundError("Домен не найден")
        return row

    async def create(self, data: DomainCreate) -> SendingDomain:
        existing = await self.db.scalar(
            select(SendingDomain).where(
                SendingDomain.workspace_id == self.workspace_id, SendingDomain.domain == data.domain
            )
        )
        if existing:
            raise ConflictError("Домен уже добавлен")
        row = SendingDomain(workspace_id=self.workspace_id, **data.model_dump())
        self.db.add(row)
        await self.db.flush()
        return row

    @audited("domain.deleted", "domain")
    async def delete(self, domain_id: UUID) -> None:
        await self.db.delete(await self.get(domain_id))

    @staticmethod
    def _txt(answer: object) -> str:
        strings = getattr(answer, "strings", None)
        if strings:
            return "".join(
                part.decode() if isinstance(part, bytes) else str(part) for part in strings
            )
        return str(answer).strip('"').replace('" "', "")

    async def _txt_records(self, name: str) -> list[str]:
        try:
            answers = await self.resolver.resolve(name, "TXT")  # type: ignore[attr-defined]
            return [self._txt(answer) for answer in answers]
        except (
            dns.resolver.NXDOMAIN,
            dns.resolver.NoAnswer,
            dns.resolver.NoNameservers,
            dns.exception.Timeout,
            OSError,
        ):
            return []

    @audited("domain.verified", "domain")
    async def verify(self, domain_id: UUID) -> DomainVerification:
        domain = await self.get(domain_id)
        root_records = await self._txt_records(domain.domain)
        spf = next((value for value in root_records if value.casefold().startswith("v=spf1")), None)
        dmarc_records = await self._txt_records(f"_dmarc.{domain.domain}")
        dmarc = next(
            (value for value in dmarc_records if value.casefold().startswith("v=dmarc1")), None
        )
        dkim_details: list[dict[str, object]] = []
        for configured in domain.dkim_records:
            selector = configured.get("selector", "").strip()
            records = (
                await self._txt_records(f"{selector}._domainkey.{domain.domain}")
                if selector
                else []
            )
            expected = configured.get("value", "").replace(" ", "")
            valid = bool(records) and (
                not expected or any(expected in value.replace(" ", "") for value in records)
            )
            dkim_details.append({"selector": selector, "valid": valid, "records": records})
        dkim_valid = bool(dkim_details) and all(bool(row["valid"]) for row in dkim_details)
        domain.spf_record, domain.dmarc_record = spf, dmarc
        domain.dkim_enabled = dkim_valid
        domain.status = "verified" if spf and dkim_valid and dmarc else "failed"
        domain.reputation_score = min(
            100, (35 if spf else 0) + (35 if dkim_valid else 0) + (30 if dmarc else 0)
        )
        verification = DomainVerification(
            domain_id=domain.id,
            spf_present=bool(spf),
            dkim_valid=dkim_valid,
            dmarc_present=bool(dmarc),
            details={
                "spf_records": root_records,
                "dkim": dkim_details,
                "dmarc_records": dmarc_records,
            },
        )
        self.db.add(verification)
        await self.db.flush()
        return verification

    async def dns_records(self, domain_id: UUID) -> dict[str, object]:
        domain = await self.get(domain_id)
        return {
            "domain": domain.domain,
            "spf": {
                "host": "@",
                "type": "TXT",
                "value": domain.spf_record or "v=spf1 include:amazonses.com ~all",
            },
            "dkim": [
                {
                    "host": f"{row.get('selector', 'mailer')}._domainkey",
                    "type": "TXT",
                    "value": row.get("value", ""),
                }
                for row in domain.dkim_records
            ],
            "dmarc": {
                "host": "_dmarc",
                "type": "TXT",
                "value": domain.dmarc_record
                or "v=DMARC1; p=none; rua=mailto:dmarc@" + domain.domain,
            },
        }

    async def reputation(self, domain_id: UUID) -> dict[str, object]:
        domain = await self.get(domain_id)
        latest = await self.db.scalar(
            select(DomainVerification)
            .where(DomainVerification.domain_id == domain.id)
            .order_by(DomainVerification.created_at.desc())
        )
        return {
            "domain": domain.domain,
            "score": domain.reputation_score,
            "status": domain.status,
            "last_checked_at": latest.created_at if latest else None,
        }
