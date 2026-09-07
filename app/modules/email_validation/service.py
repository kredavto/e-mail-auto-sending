from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from typing import Protocol, cast
from uuid import UUID

import aiosmtplib
import dns.asyncresolver
import httpx
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.resilience import IntegrationError
from app.modules.email_validation.models import EmailValidationResult
from app.modules.hunter.service import HunterService

DISPOSABLE_DOMAINS = {
    "10minutemail.com",
    "guerrillamail.com",
    "mailinator.com",
    "temp-mail.org",
    "tempmail.com",
    "throwawaymail.com",
    "yopmail.com",
}
ROLE_LOCAL_PARTS = {
    "admin",
    "billing",
    "contact",
    "hello",
    "info",
    "office",
    "sales",
    "support",
    "team",
}
SPAM_TRAP_LOCAL_PARTS = {"spamtrap", "honeypot", "trap", "abuse", "postmaster"}


@dataclass
class ValidationData:
    email: str
    status: str = "unknown"
    score: int = 0
    is_disposable: bool = False
    is_role_based: bool = False
    has_mx_records: bool = False
    smtp_check_passed: bool = False
    is_spam_trap: bool = False
    provider: str = "internal"
    details: dict[str, object] = field(default_factory=dict)


class ValidationProvider(Protocol):
    name: str

    async def validate(self, email: str) -> ValidationData | None: ...


class HunterValidationProvider:
    name = "hunter"

    def __init__(self, hunter: HunterService | None = None) -> None:
        self.hunter = hunter or HunterService()

    async def validate(self, email: str) -> ValidationData | None:
        try:
            row = await self.hunter.verify(email)
        except (IntegrationError, OSError, TimeoutError):
            return None
        score = int(str(row.get("score", 0)))
        raw_status = str(row.get("status", "unknown"))
        status = (
            "valid"
            if raw_status in {"valid", "accept_all"} and score >= 70
            else ("invalid" if raw_status == "invalid" else "risky")
        )
        return ValidationData(
            email=email,
            status=status,
            score=score,
            provider=self.name,
            details={"hunter_status": raw_status},
        )


class NeverBounceValidationProvider:
    name = "neverbounce"

    def __init__(self, api_key: str | None = None, api_url: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.neverbounce_api_key
        self.api_url = (api_url or settings.neverbounce_api_url).rstrip("/")

    async def validate(self, email: str) -> ValidationData | None:
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{self.api_url}/single/check",
                    params={"key": self.api_key, "email": email, "timeout": 10},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        result = str(payload.get("result", "unknown"))
        flags = {str(value) for value in payload.get("flags", [])}
        scores = {"valid": 100, "catchall": 65, "unknown": 50, "invalid": 0, "disposable": 0}
        status = (
            "valid"
            if result == "valid"
            else ("invalid" if result in {"invalid", "disposable"} else "risky")
        )
        return ValidationData(
            email=email,
            status=status,
            score=scores.get(result, 50),
            is_disposable=result == "disposable" or "disposable_email" in flags,
            is_role_based="role_account" in flags,
            has_mx_records="has_dns_mx" in flags,
            smtp_check_passed="smtp_connectable" in flags,
            is_spam_trap="spamtrap_network" in flags,
            provider=self.name,
            details={"neverbounce_result": result, "flags": sorted(flags)},
        )


class EmailValidationService:
    def __init__(
        self,
        db: AsyncSession | None = None,
        workspace_id: UUID | None = None,
        *,
        resolver: object | None = None,
        providers: list[ValidationProvider] | None = None,
    ) -> None:
        self.db, self.workspace_id = db, workspace_id
        self.resolver = resolver or dns.asyncresolver.Resolver()
        self.providers: list[ValidationProvider] = (
            providers
            if providers is not None
            else [
                HunterValidationProvider(),
                NeverBounceValidationProvider(),
            ]
        )

    async def _has_mx(self, domain: str) -> tuple[bool, list[str]]:
        try:
            answers = await self.resolver.resolve(domain, "MX")  # type: ignore[attr-defined]
            hosts = [str(getattr(answer, "exchange", answer)).rstrip(".") for answer in answers]
            return bool(hosts), hosts
        except (
            dns.resolver.NXDOMAIN,
            dns.resolver.NoAnswer,
            dns.resolver.NoNameservers,
            dns.exception.Timeout,
            OSError,
        ):
            return False, []

    async def _smtp_check(self, email: str, mx_hosts: list[str]) -> bool:
        if not mx_hosts:
            return False
        try:
            client = aiosmtplib.SMTP(hostname=mx_hosts[0], port=25, timeout=8)
            await client.connect()
            await client.helo(hostname="validator.local")
            await client.mail("verify@validator.local")
            code, _ = await client.rcpt(email)
            await client.quit()
            return 200 <= int(code) < 300
        except (OSError, TimeoutError, smtplib.SMTPException, aiosmtplib.SMTPException):
            return False

    async def validate(
        self, raw_email: str, *, smtp_check: bool = False, persist: bool = True
    ) -> EmailValidationResult | ValidationData:
        email = raw_email.strip().casefold()
        try:
            email = validate_email(email, check_deliverability=False).normalized
        except EmailNotValidError as exc:
            result = ValidationData(
                email=email, status="invalid", score=0, details={"syntax_error": str(exc)}
            )
            return await self._persist(result) if persist and self.db else result

        local, domain = email.rsplit("@", 1)
        has_mx, hosts = await self._has_mx(domain)
        disposable = domain in DISPOSABLE_DOMAINS
        role_based = local in ROLE_LOCAL_PARTS
        spam_trap = local in SPAM_TRAP_LOCAL_PARTS or local.startswith("spamtrap+")
        smtp_passed = await self._smtp_check(email, hosts) if smtp_check else False
        score = 100
        score -= 55 if not has_mx else 0
        score -= 45 if disposable else 0
        score -= 20 if role_based else 0
        score -= 80 if spam_trap else 0
        if smtp_check and not smtp_passed:
            score -= 30
        score = max(0, score)
        status = (
            "invalid"
            if not has_mx or disposable or spam_trap
            else ("risky" if role_based or (smtp_check and not smtp_passed) else "valid")
        )
        result = ValidationData(
            email=email,
            status=status,
            score=score,
            is_disposable=disposable,
            is_role_based=role_based,
            has_mx_records=has_mx,
            smtp_check_passed=smtp_passed,
            is_spam_trap=spam_trap,
            details={"mx_hosts": hosts, "smtp_checked": smtp_check},
        )
        # A valid internal verdict is sufficient. Risky/unknown results fall through to providers.
        if status != "valid" and has_mx and not disposable and not spam_trap:
            for provider in self.providers:
                external = await provider.validate(email)
                if external and external.score > result.score:
                    external.is_disposable = disposable
                    external.is_role_based = role_based
                    external.has_mx_records = has_mx
                    external.is_spam_trap = spam_trap
                    if role_based:
                        external.status = "risky"
                    external.details = {**result.details, **external.details}
                    result = external
                    break
        return await self._persist(result) if persist and self.db else result

    async def _persist(self, data: ValidationData) -> EmailValidationResult:
        assert self.db is not None and self.workspace_id is not None
        row = await self.db.scalar(
            select(EmailValidationResult).where(
                EmailValidationResult.workspace_id == self.workspace_id,
                EmailValidationResult.email == data.email,
            )
        )
        values = data.__dict__
        if row:
            for key, value in values.items():
                setattr(row, key, value)
        else:
            row = EmailValidationResult(workspace_id=self.workspace_id, **values)
            self.db.add(row)
        await self.db.flush()
        return row

    async def latest(self, email: str) -> EmailValidationResult | None:
        if not self.db or not self.workspace_id:
            return None
        return cast(
            EmailValidationResult | None,
            await self.db.scalar(
                select(EmailValidationResult).where(
                    EmailValidationResult.workspace_id == self.workspace_id,
                    EmailValidationResult.email == email.strip().casefold(),
                )
            ),
        )

    async def stats(self) -> dict[str, object]:
        if not self.db or not self.workspace_id:
            return {"total": 0, "by_status": {}}
        rows = list(
            (
                await self.db.scalars(
                    select(EmailValidationResult).where(
                        EmailValidationResult.workspace_id == self.workspace_id
                    )
                )
            ).all()
        )
        statuses = {
            status: sum(row.status == status for row in rows)
            for status in ("valid", "invalid", "risky", "unknown")
        }
        return {
            "total": len(rows),
            "by_status": statuses,
            "average_score": sum(row.score for row in rows) / len(rows) if rows else 0,
        }
