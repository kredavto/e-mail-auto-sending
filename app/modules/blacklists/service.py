from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from uuid import UUID

import dns.asyncresolver
import dns.exception
import dns.resolver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import IntegrationEvent, publish_enterprise_event
from app.core.exceptions import NotFoundError
from app.modules.blacklists.models import BlacklistAlert, BlacklistCheck, BlacklistSubscription
from app.modules.domains.models import SendingDomain


@dataclass
class BlacklistResult:
    blacklist: str
    listed: bool
    return_code: str | None = None
    error: str | None = None


class BlacklistMonitor:
    BLACKLISTS = [
        {"name": "Spamhaus", "dns_zone": "zen.spamhaus.org"},
        {"name": "Barracuda", "dns_zone": "b.barracudacentral.org"},
        {"name": "SURBL", "dns_zone": "multi.surbl.org"},
        {"name": "URIBL", "dns_zone": "multi.uribl.com"},
        {"name": "SORBS", "dns_zone": "dnsbl.sorbs.net"},
        {"name": "Mailspike", "dns_zone": "bl.mailspike.net"},
        {"name": "Invaluement", "dns_zone": "dnsbl.invaluement.com"},
        {"name": "Lashback", "dns_zone": "ubl.unsubscore.com"},
    ]

    def __init__(self, resolver: object | None = None) -> None:
        self.resolver = resolver or dns.asyncresolver.Resolver()

    async def check_ip(self, ip: str) -> list[BlacklistResult]:
        address = ipaddress.ip_address(ip)
        if address.version != 4:
            return [
                BlacklistResult(row["name"], False, error="IPv6 DNSBL is not supported")
                for row in self.BLACKLISTS
            ]
        reversed_ip = ".".join(reversed(ip.split(".")))
        results: list[BlacklistResult] = []
        for blacklist in self.BLACKLISTS:
            try:
                answers = await self.resolver.resolve(  # type: ignore[attr-defined]
                    f"{reversed_ip}.{blacklist['dns_zone']}", "A"
                )
                results.append(BlacklistResult(blacklist["name"], True, str(answers[0])))
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                results.append(BlacklistResult(blacklist["name"], False))
            except (dns.resolver.NoNameservers, dns.exception.Timeout, OSError) as exc:
                results.append(BlacklistResult(blacklist["name"], False, error=str(exc)))
        return results


class BlacklistService:
    def __init__(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        monitor: BlacklistMonitor | None = None,
        resolver: object | None = None,
    ) -> None:
        self.db, self.workspace_id = db, workspace_id
        self.resolver = resolver or dns.asyncresolver.Resolver()
        self.monitor = monitor or BlacklistMonitor(self.resolver)

    async def _domain(self, domain_id: UUID) -> SendingDomain:
        row = await self.db.scalar(
            select(SendingDomain).where(
                SendingDomain.id == domain_id, SendingDomain.workspace_id == self.workspace_id
            )
        )
        if not row:
            raise NotFoundError("Домен не найден")
        return row

    async def check(self, domain_id: UUID) -> list[BlacklistCheck]:
        domain = await self._domain(domain_id)
        try:
            answers = await self.resolver.resolve(domain.domain, "A")  # type: ignore[attr-defined]
            ips = sorted({str(answer) for answer in answers})
        except (
            dns.resolver.NXDOMAIN,
            dns.resolver.NoAnswer,
            dns.resolver.NoNameservers,
            dns.exception.Timeout,
            OSError,
        ):
            ips = []
        checks: list[BlacklistCheck] = []
        for ip in ips:
            for result in await self.monitor.check_ip(ip):
                row = BlacklistCheck(
                    domain_id=domain.id,
                    ip_address=ip,
                    blacklist=result.blacklist,
                    listed=result.listed,
                    return_code=result.return_code,
                    error=result.error,
                )
                self.db.add(row)
                checks.append(row)
                if result.listed:
                    self.db.add(
                        BlacklistAlert(
                            workspace_id=self.workspace_id,
                            domain_id=domain.id,
                            blacklist=result.blacklist,
                            ip_address=ip,
                            message=f"{domain.domain} ({ip}) обнаружен в {result.blacklist}",
                        )
                    )
                    await self.db.flush()
                    await publish_enterprise_event(
                        self.db,
                        IntegrationEvent(
                            workspace_id=self.workspace_id,
                            resource_type="domain",
                            resource_id=domain.id,
                            data={
                                "domain": domain.domain,
                                "ip_address": ip,
                                "blacklist": result.blacklist,
                            },
                            kind="blacklist.detected",
                        ),
                    )
        listed_count = sum(row.listed for row in checks)
        if checks:
            domain.reputation_score = max(0, domain.reputation_score - listed_count * 15)
        await self.db.flush()
        return checks

    async def history(self, domain_id: UUID) -> list[BlacklistCheck]:
        await self._domain(domain_id)
        return list(
            (
                await self.db.scalars(
                    select(BlacklistCheck)
                    .where(BlacklistCheck.domain_id == domain_id)
                    .order_by(BlacklistCheck.created_at.desc())
                    .limit(1000)
                )
            ).all()
        )

    async def subscribe(self, domain_id: UUID, email: str) -> BlacklistSubscription:
        await self._domain(domain_id)
        normalized = email.casefold()
        row = await self.db.scalar(
            select(BlacklistSubscription).where(
                BlacklistSubscription.domain_id == domain_id,
                BlacklistSubscription.notification_email == normalized,
            )
        )
        if row:
            row.is_active = True
            return row
        row = BlacklistSubscription(
            workspace_id=self.workspace_id, domain_id=domain_id, notification_email=normalized
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def alerts(self) -> list[BlacklistAlert]:
        return list(
            (
                await self.db.scalars(
                    select(BlacklistAlert)
                    .where(
                        BlacklistAlert.workspace_id == self.workspace_id,
                        BlacklistAlert.acknowledged.is_(False),
                    )
                    .order_by(BlacklistAlert.created_at.desc())
                )
            ).all()
        )
