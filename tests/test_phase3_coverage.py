from __future__ import annotations

from collections import deque
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import dns.exception
import dns.resolver
import pytest

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.integrations.resilience import IntegrationError
from app.modules.ab_testing.models import ABTest, ABTestAssignment, ABTestVariant
from app.modules.ab_testing.schemas import ABTestCreate, VariantCreate
from app.modules.ab_testing.service import ABTestingService
from app.modules.analytics.models import AnalyticsReport, DailyMetric
from app.modules.analytics.schemas import GenerateReportRequest
from app.modules.analytics.service import AnalyticsService
from app.modules.blacklists.models import BlacklistSubscription
from app.modules.blacklists.service import BlacklistMonitor, BlacklistResult, BlacklistService
from app.modules.contacts.models import Contact
from app.modules.domains.models import SendingDomain
from app.modules.domains.schemas import DomainCreate
from app.modules.domains.service import DomainService
from app.modules.email_validation.models import EmailValidationResult
from app.modules.email_validation.service import (
    EmailValidationService,
    HunterValidationProvider,
    NeverBounceValidationProvider,
    ValidationData,
)
from app.modules.enrichment.models import EnrichmentResult
from app.modules.enrichment.service import EnrichmentOrchestrator
from app.modules.linkedin.models import LinkedInProfile
from app.modules.quality.service import QualityChecker
from app.modules.sender.models import EmailMessage
from app.modules.tenchat.models import TenchatProfile
from app.modules.warmup.models import WarmupPlan
from app.modules.warmup.schemas import WarmupStart
from app.modules.warmup.service import WarmupService

WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
OTHER_WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000002")


class Rows:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class FakeDB:
    def __init__(
        self,
        *,
        scalar: list[object] | None = None,
        scalars: list[list[object]] | None = None,
        gets: list[object] | None = None,
    ) -> None:
        self.scalar_values = deque(scalar or [])
        self.scalars_values = deque(scalars or [])
        self.get_values = deque(gets or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flush_count = 0

    async def scalar(self, _query: object) -> object | None:
        return self.scalar_values.popleft() if self.scalar_values else None

    async def scalars(self, _query: object) -> Rows:
        return Rows(self.scalars_values.popleft() if self.scalars_values else [])

    async def get(self, _model: object, _identifier: object) -> object | None:
        return self.get_values.popleft() if self.get_values else None

    def add(self, row: object) -> None:
        if getattr(row, "id", None) is None:
            row.id = uuid4()
        self.added.append(row)

    def add_all(self, rows: list[object]) -> None:
        for row in rows:
            self.add(row)

    async def flush(self) -> None:
        self.flush_count += 1

    async def delete(self, row: object) -> None:
        self.deleted.append(row)


def ab_variant(key: str, sent: int, replies: int) -> ABTestVariant:
    return ABTestVariant(
        id=uuid4(),
        test_id=uuid4(),
        variant_key=key,
        sent_count=sent,
        replied_count=replies,
        opened_count=0,
        clicked_count=0,
        meeting_count=0,
        open_rate=0,
        reply_rate=replies / sent if sent else 0,
        click_rate=0,
        meeting_rate=0,
        p_value=1,
    )


def ab_test(**overrides: object) -> ABTest:
    values: dict[str, object] = {
        "id": uuid4(),
        "workspace_id": WORKSPACE_ID,
        "campaign_id": uuid4(),
        "name": "Subject",
        "test_type": "subject",
        "status": "draft",
        "split_ratio": 0.5,
        "sample_size": 2,
        "confidence_level": 0.95,
        "primary_metric": "reply_rate",
        "min_detectable_effect": 0.1,
        "winner_variant": None,
    }
    values.update(overrides)
    return ABTest(**values)


def sending_domain(**overrides: object) -> SendingDomain:
    values: dict[str, object] = {
        "id": uuid4(),
        "workspace_id": WORKSPACE_ID,
        "domain": "example.com",
        "status": "pending",
        "dkim_enabled": False,
        "dkim_records": [{"selector": "mail", "value": "v=DKIM1;p=abc"}],
        "spf_record": None,
        "dmarc_record": None,
        "daily_limit": 200,
        "current_daily_count": 0,
        "daily_count_date": None,
        "reputation_score": 100,
    }
    values.update(overrides)
    return SendingDomain(**values)


def warmup_plan(**overrides: object) -> WarmupPlan:
    values: dict[str, object] = {
        "id": uuid4(),
        "domain_id": uuid4(),
        "start_date": date.today() - timedelta(days=3),
        "current_daily_limit": 20,
        "target_daily_limit": 40,
        "increment_percent": 0.2,
        "status": "active",
        "provider": "internal",
    }
    values.update(overrides)
    return WarmupPlan(**values)


def daily(day: date, sent: int = 10) -> DailyMetric:
    return DailyMetric(
        id=uuid4(),
        workspace_id=WORKSPACE_ID,
        campaign_id=uuid4(),
        product_id=uuid4(),
        date=day,
        sent_count=sent,
        delivered_count=sent - 1,
        opened_count=5,
        clicked_count=2,
        replied_count=1,
        bounced_count=1,
        meeting_count=1,
    )


def test_ab_statistical_edge_cases() -> None:
    service = ABTestingService()
    zero = ab_variant("A", 0, 0)
    assert service.frequentist_analysis(zero, zero, "reply_rate")["winner"] is None
    with pytest.raises(ValueError):
        service.frequentist_analysis(zero, zero, "invalid")
    with pytest.raises(ValueError):
        service.bayesian_analysis(zero, zero, "invalid", 10)
    with pytest.raises(ValueError):
        service.calculate_required_sample_size(0, 0.1)
    with pytest.raises(ValueError):
        service.calculate_required_sample_size(0.9999999999, 1e-20)
    with pytest.raises(RuntimeError):
        service._require_db()
    with pytest.raises(AppError):
        service.analyze_variants([zero], "reply_rate")


@pytest.mark.asyncio
async def test_ab_crud_lifecycle_and_assignment() -> None:
    test = ab_test()
    contacts = [uuid4(), uuid4()]
    db = FakeDB(scalar=[test], scalars=[contacts])
    service = ABTestingService(db, WORKSPACE_ID)  # type: ignore[arg-type]
    started = await service.start(test.id)
    assert started.status == "running"
    assert len(db.added) == 2
    db.scalar_values.extend([test, test])
    assert await service.stop(test.id) is test
    with pytest.raises(ConflictError):
        await service.stop(test.id)

    contact = SimpleNamespace(workspace_id=WORKSPACE_ID)
    existing = ABTestAssignment(
        id=uuid4(), test_id=test.id, contact_id=contacts[0], variant_key="A"
    )
    test.status = "running"
    db = FakeDB(scalar=[test, existing], gets=[contact])
    service = ABTestingService(db, WORKSPACE_ID)  # type: ignore[arg-type]
    assert await service.assignment(test.id, contacts[0]) is existing
    db = FakeDB(scalar=[test, None], gets=[contact])
    created = await ABTestingService(db, WORKSPACE_ID).assignment(test.id, contacts[1])  # type: ignore[arg-type]
    assert created.variant_key in {"A", "B"}


@pytest.mark.asyncio
async def test_ab_create_results_winner_and_apply() -> None:
    campaign = SimpleNamespace(workspace_id=WORKSPACE_ID, sender_name="Old", sequence_id=uuid4())
    create = ABTestCreate(
        campaign_id=uuid4(),
        name="Names",
        test_type="sender_name",
        variants=[
            VariantCreate(variant_key="A", sender_name="Anna"),
            VariantCreate(variant_key="B", sender_name="Boris"),
        ],
    )
    db = FakeDB(gets=[campaign])
    service = ABTestingService(db, WORKSPACE_ID)  # type: ignore[arg-type]
    made = await service.create(create)
    assert made.name == "Names" and len(db.added) == 3

    wrong_db = FakeDB(gets=[SimpleNamespace(workspace_id=OTHER_WORKSPACE_ID)])
    with pytest.raises(NotFoundError):
        await ABTestingService(wrong_db, WORKSPACE_ID).create(create)  # type: ignore[arg-type]

    test = ab_test(status="running")
    variants = [ab_variant("A", 100, 5), ab_variant("B", 100, 20)]
    service = ABTestingService(FakeDB(), WORKSPACE_ID)  # type: ignore[arg-type]
    service.get = AsyncMock(return_value=test)  # type: ignore[method-assign]
    service.variants = AsyncMock(return_value=variants)  # type: ignore[method-assign]
    results = await service.results(test.id)
    assert results["automatic_winner"] == "B"
    selected = await service.select_winner(test.id)
    assert selected.winner_variant == "B" and selected.status == "completed"

    test.winner_variant = None
    with pytest.raises(ConflictError):
        await service.apply_winner(test.id)
    test.winner_variant = "B"
    test.test_type = "sender_name"
    variants[1].sender_name = "Boris"
    variants[1].template_id = uuid4()
    variants[1].subject = "Winner"
    step = SimpleNamespace(template_id=None, config={})
    campaign = SimpleNamespace(sender_name="Old", sequence_id=uuid4())
    db = FakeDB(scalars=[[step]], gets=[campaign])
    service.db = db  # type: ignore[assignment]
    await service.apply_winner(test.id)
    assert campaign.sender_name == "Boris"
    assert step.template_id == variants[1].template_id
    assert step.config["subject_override"] == "Winner"


@pytest.mark.asyncio
async def test_ab_update_metrics_auto_completes() -> None:
    test = ab_test(status="running", sample_size=2, confidence_level=0.8)
    a, b = ab_variant("A", 0, 0), ab_variant("B", 0, 0)
    contact_a, contact_b = uuid4(), uuid4()
    assignments = [
        ABTestAssignment(test_id=test.id, contact_id=contact_a, variant_key="A"),
        ABTestAssignment(test_id=test.id, contact_id=contact_b, variant_key="B"),
    ]
    now = datetime.now(UTC)
    messages = [
        EmailMessage(
            contact_id=contact_a,
            campaign_id=test.campaign_id,
            recipient_email="a@x.io",
            subject="a",
            status="sent",
            sent_at=now,
        ),
        EmailMessage(
            contact_id=contact_b,
            campaign_id=test.campaign_id,
            recipient_email="b@x.io",
            subject="b",
            status="sent",
            sent_at=now,
            opened_at=now,
            clicked_at=now,
        ),
    ]
    contacts = [
        SimpleNamespace(id=contact_a, has_replied=False, status="new"),
        SimpleNamespace(id=contact_b, has_replied=True, status="meeting_booked"),
    ]
    variants = [a, b]
    db = FakeDB(scalars=[assignments, messages, contacts])
    service = ABTestingService(db, WORKSPACE_ID)  # type: ignore[arg-type]
    service.get = AsyncMock(return_value=test)  # type: ignore[method-assign]
    service.variants = AsyncMock(return_value=variants)  # type: ignore[method-assign]
    result = await service.update_metrics(test.id)
    assert result["automatic_winner"] == "B"
    assert b.reply_rate == 1 and b.meeting_rate == 1
    assert test.status == "completed"


class MxAnswer:
    exchange = "mx.example.com."


class MxResolver:
    async def resolve(self, _name: str, _kind: str) -> list[object]:
        return [MxAnswer()]


class Provider:
    name = "provider"

    async def validate(self, email: str) -> ValidationData:
        return ValidationData(email=email, status="valid", score=99, provider=self.name)


@pytest.mark.asyncio
async def test_validation_providers_and_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    hunter = SimpleNamespace(verify=AsyncMock(return_value={"score": "95", "status": "valid"}))
    result = await HunterValidationProvider(hunter).validate("a@example.com")
    assert result and result.status == "valid"
    hunter.verify = AsyncMock(side_effect=IntegrationError("down"))
    assert await HunterValidationProvider(hunter).validate("a@example.com") is None

    assert await NeverBounceValidationProvider(api_key="").validate("a@example.com") is None

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"result": "valid", "flags": ["has_dns_mx", "smtp_connectable"]}

    class Client:
        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(
        "app.modules.email_validation.service.httpx.AsyncClient", lambda **_kw: Client()
    )
    neverbounce = await NeverBounceValidationProvider(api_key="key").validate("a@example.com")
    assert neverbounce and neverbounce.smtp_check_passed and neverbounce.status == "valid"

    class SMTP:
        async def connect(self) -> None:
            pass

        async def helo(self, **_kwargs: object) -> None:
            pass

        async def mail(self, _sender: str) -> None:
            pass

        async def rcpt(self, _email: str) -> tuple[int, str]:
            return 250, "ok"

        async def quit(self) -> None:
            pass

    monkeypatch.setattr(
        "app.modules.email_validation.service.aiosmtplib.SMTP", lambda **_kw: SMTP()
    )
    service = EmailValidationService(resolver=MxResolver(), providers=[])
    assert await service._smtp_check("a@example.com", []) is False
    assert await service._smtp_check("a@example.com", ["mx.example.com"]) is True


@pytest.mark.asyncio
async def test_validation_fallback_persistence_latest_and_stats() -> None:
    service = EmailValidationService(resolver=MxResolver(), providers=[Provider()])
    valid = await service.validate("USER@example.com", persist=False)
    assert isinstance(valid, ValidationData) and valid.status == "valid" and valid.score == 100
    role = await service.validate("INFO@example.com", persist=False)
    assert (
        isinstance(role, ValidationData) and role.provider == "provider" and role.status == "risky"
    )
    trap = await service.validate("spamtrap@example.com", persist=False)
    assert isinstance(trap, ValidationData) and trap.is_spam_trap and trap.status == "invalid"

    existing = EmailValidationResult(
        workspace_id=WORKSPACE_ID,
        email="a@example.com",
        status="unknown",
        score=0,
        is_disposable=False,
        is_role_based=False,
        has_mx_records=True,
        smtp_check_passed=False,
        is_spam_trap=False,
        provider="internal",
        details={},
    )
    db = FakeDB(scalar=[None, existing, existing], scalars=[[existing]])
    persisted = EmailValidationService(db, WORKSPACE_ID, resolver=MxResolver(), providers=[])
    created = await persisted.validate("new@example.com")
    assert isinstance(created, EmailValidationResult)
    updated = await persisted._persist(ValidationData("a@example.com", "valid", 100))
    assert updated is existing and existing.score == 100
    assert await persisted.latest("A@example.com") is existing
    stats = await persisted.stats()
    assert stats["total"] == 1 and stats["average_score"] == 100
    assert await EmailValidationService().latest("x@example.com") is None
    assert (await EmailValidationService().stats())["total"] == 0


class EnrichmentValidator:
    async def validate(self, email: str, **kwargs: object) -> ValidationData:
        return ValidationData(
            email=email,
            status="valid",
            score=92,
            smtp_check_passed=bool(kwargs.get("smtp_check", False)),
            has_mx_records=True,
        )


@pytest.mark.asyncio
async def test_enrichment_patterns_sources_and_contact() -> None:
    contact = Contact(
        id=uuid4(),
        workspace_id=WORKSPACE_ID,
        email="old@placeholder.invalid",
        first_name="John",
        last_name="Doe",
        company="Acme",
        current_site_url="https://www.example.com/path",
        custom_fields={},
        source="manual",
    )
    assert EnrichmentOrchestrator.extract_domain(contact) == "example.com"
    assert EnrichmentOrchestrator._name("Jöhn-Doe") == "jhndoe"
    db = FakeDB()
    service = EnrichmentOrchestrator(
        db,
        WORKSPACE_ID,
        hunter=SimpleNamespace(),
        validator=EnrichmentValidator(),  # type: ignore[arg-type]
    )
    assert len(await service._patterns(contact, "example.com")) == 3
    contact.first_name = ""
    assert await service._patterns(contact, "example.com") == []
    contact.first_name = "John"

    linkedin = LinkedInProfile(
        workspace_id=WORKSPACE_ID,
        contact_id=contact.id,
        linkedin_id="1",
        email="li@example.com",
        email_confidence=80,
        profile_url="https://linkedin.test/1",
    )
    tenchat = TenchatProfile(
        workspace_id=WORKSPACE_ID,
        contact_id=contact.id,
        tenchat_user_id="t1",
        email="tc@example.com",
    )
    hunter = SimpleNamespace(
        find_confident_email=AsyncMock(
            return_value={"email": "hunter@example.com", "confidence": 99}
        )
    )
    db = FakeDB(scalar=[linkedin, tenchat])
    service = EnrichmentOrchestrator(
        db,
        WORKSPACE_ID,
        hunter=hunter,
        validator=EnrichmentValidator(),  # type: ignore[arg-type]
    )
    enriched = await service.enrich_contact(contact)
    assert enriched.source == "hunter" and contact.email == "hunter@example.com"
    assert db.flush_count == 1
    contact.workspace_id = OTHER_WORKSPACE_ID
    with pytest.raises(NotFoundError):
        await service.enrich_contact(contact)


@pytest.mark.asyncio
async def test_enrichment_lookup_stats_and_empty_domain() -> None:
    contact = Contact(
        id=uuid4(),
        workspace_id=WORKSPACE_ID,
        email="a@example.com",
        first_name="",
        last_name="",
        company="Acme Inc",
        current_site_url=None,
        custom_fields={},
        source="manual",
    )
    assert EnrichmentOrchestrator.extract_domain(contact) is None
    db = FakeDB(gets=[None])
    service = EnrichmentOrchestrator(db, WORKSPACE_ID)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.enrich(contact.id)
    found = EnrichmentResult(
        workspace_id=WORKSPACE_ID,
        contact_id=contact.id,
        email="x@example.com",
        source="hunter",
        confidence=80,
        enriched_data={},
    )
    missing = EnrichmentResult(
        workspace_id=WORKSPACE_ID,
        contact_id=contact.id,
        email=None,
        source=None,
        confidence=0,
        enriched_data={},
    )
    db = FakeDB(scalars=[[found, missing]])
    stats = await EnrichmentOrchestrator(db, WORKSPACE_ID).stats()  # type: ignore[arg-type]
    assert stats["success_rate"] == 0.5
    assert len(EnrichmentOrchestrator.sources()) == 4


class TxtResolver:
    async def resolve(self, name: str, _kind: str) -> list[object]:
        if name == "example.com":
            return ['"v=spf1 include:test ~all"']
        if name.startswith("_dmarc"):
            return ['"v=DMARC1; p=reject"']
        if name.startswith("mail._domainkey"):
            return ['"v=DKIM1;p=abc"']
        raise dns.resolver.NXDOMAIN


@pytest.mark.asyncio
async def test_domains_crud_verify_records_and_reputation() -> None:
    domain = sending_domain()
    db = FakeDB(scalar=[domain])
    service = DomainService(db, WORKSPACE_ID, resolver=TxtResolver())  # type: ignore[arg-type]
    verified = await service.verify(domain.id)
    assert verified.spf_present and verified.dkim_valid and verified.dmarc_present
    assert domain.status == "verified" and domain.reputation_score == 100
    assert DomainService._txt(SimpleNamespace(strings=[b"v=spf1", b" ~all"])) == "v=spf1 ~all"

    service.get = AsyncMock(return_value=domain)  # type: ignore[method-assign]
    records = await service.dns_records(domain.id)
    assert records["domain"] == "example.com"
    latest = SimpleNamespace(created_at=datetime.now(UTC))
    db.scalar_values.append(latest)
    reputation = await service.reputation(domain.id)
    assert reputation["last_checked_at"] == latest.created_at

    list_db = FakeDB(scalars=[[domain]])
    assert await DomainService(list_db, WORKSPACE_ID).list_all() == [domain]  # type: ignore[arg-type]
    absent = DomainService(FakeDB(scalar=[None]), WORKSPACE_ID)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await absent.get(domain.id)


@pytest.mark.asyncio
async def test_domains_create_conflict_delete_and_dns_failure() -> None:
    data = DomainCreate(domain="new.example", daily_limit=50)
    existing = sending_domain()
    with pytest.raises(ConflictError):
        await DomainService(FakeDB(scalar=[existing]), WORKSPACE_ID).create(data)  # type: ignore[arg-type]
    db = FakeDB(scalar=[None])
    created = await DomainService(db, WORKSPACE_ID).create(data)  # type: ignore[arg-type]
    assert created.domain == "new.example" and db.flush_count == 1
    service = DomainService(db, WORKSPACE_ID)  # type: ignore[arg-type]
    service.get = AsyncMock(return_value=created)  # type: ignore[method-assign]
    await service.delete(created.id)
    assert db.deleted == [created]

    class BrokenResolver:
        async def resolve(self, _name: str, _kind: str) -> list[object]:
            raise dns.exception.Timeout

    assert await DomainService(db, WORKSPACE_ID, resolver=BrokenResolver())._txt_records("x") == []  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_warmup_full_lifecycle_and_errors() -> None:
    domain = sending_domain(daily_limit=100)
    data = WarmupStart(domain_id=domain.id, target_daily_limit=80, increment_percent=0.2)
    db = FakeDB(scalar=[domain, None])
    service = WarmupService(db, WORKSPACE_ID)  # type: ignore[arg-type]
    plan = await service.start(data)
    assert plan.current_daily_limit == 20 and plan.target_daily_limit == 80
    service.get = AsyncMock(return_value=plan)  # type: ignore[method-assign]
    assert (await service.pause(domain.id)).status == "paused"
    with pytest.raises(ConflictError):
        await service.pause(domain.id)
    completed = await service.complete(domain.id)
    assert completed.status == "completed" and completed.current_daily_limit == 80
    assert await service.advance(completed) is completed
    plan.status = "active"
    plan.target_daily_limit = 25
    advanced = await service.advance(plan, plan.start_date + timedelta(days=10))
    assert advanced.status == "completed"
    assert (await service.schedule(domain.id))[-1]["daily_limit"] == 25

    existing = warmup_plan(status="paused")
    db = FakeDB(scalar=[domain, existing])
    restarted = await WarmupService(db, WORKSPACE_ID).start(data)  # type: ignore[arg-type]
    assert restarted.status == "active"
    db = FakeDB(scalar=[domain, warmup_plan(status="active")])
    with pytest.raises(ConflictError):
        await WarmupService(db, WORKSPACE_ID).start(data)  # type: ignore[arg-type]

    with pytest.raises(NotFoundError):
        await WarmupService(FakeDB(scalar=[None]), WORKSPACE_ID)._domain(domain.id)  # type: ignore[arg-type]
    db = FakeDB(scalar=[domain, None])
    with pytest.raises(NotFoundError):
        await WarmupService(db, WORKSPACE_ID).get(domain.id)  # type: ignore[arg-type]


class MixedBlacklistResolver:
    def __init__(self) -> None:
        self.calls = 0

    async def resolve(self, _name: str, _kind: str) -> list[str]:
        self.calls += 1
        if self.calls == 1:
            raise dns.resolver.NXDOMAIN
        if self.calls == 2:
            raise dns.exception.Timeout
        return ["127.0.0.2"]


@pytest.mark.asyncio
async def test_blacklist_monitor_and_service_lifecycle() -> None:
    ipv6 = await BlacklistMonitor().check_ip("2001:db8::1")
    assert all(row.error for row in ipv6)
    mixed = await BlacklistMonitor(MixedBlacklistResolver()).check_ip("192.0.2.10")
    assert any(not row.listed and not row.error for row in mixed)
    assert any(row.error for row in mixed)
    assert any(row.listed for row in mixed)

    domain = sending_domain(reputation_score=80)

    class AResolver:
        async def resolve(self, _name: str, _kind: str) -> list[str]:
            return ["192.0.2.1"]

    monitor = SimpleNamespace(
        check_ip=AsyncMock(
            return_value=[
                BlacklistResult("One", True, "127.0.0.2"),
                BlacklistResult("Two", False),
            ]
        )
    )
    db = FakeDB(scalar=[domain])
    service = BlacklistService(db, WORKSPACE_ID, monitor=monitor, resolver=AResolver())  # type: ignore[arg-type]
    checks = await service.check(domain.id)
    assert len(checks) == 2 and domain.reputation_score == 65
    assert len(db.added) == 3

    service._domain = AsyncMock(return_value=domain)  # type: ignore[method-assign]
    db.scalars_values.extend([[*checks], [SimpleNamespace()]])
    assert await service.history(domain.id) == checks
    alerts = await service.alerts()
    assert len(alerts) == 1

    subscription = BlacklistSubscription(
        workspace_id=WORKSPACE_ID,
        domain_id=domain.id,
        notification_email="a@example.com",
        is_active=False,
    )
    db.scalar_values.append(subscription)
    assert (await service.subscribe(domain.id, "A@Example.com")).is_active
    db.scalar_values.append(None)
    new_subscription = await service.subscribe(domain.id, "B@Example.com")
    assert new_subscription.notification_email == "b@example.com"


@pytest.mark.asyncio
async def test_blacklist_domain_errors_and_empty_dns() -> None:
    domain = sending_domain()
    with pytest.raises(NotFoundError):
        await BlacklistService(FakeDB(scalar=[None]), WORKSPACE_ID)._domain(domain.id)  # type: ignore[arg-type]

    class BrokenResolver:
        async def resolve(self, _name: str, _kind: str) -> list[str]:
            raise dns.resolver.NoAnswer

    db = FakeDB(scalar=[domain])
    rows = await BlacklistService(db, WORKSPACE_ID, resolver=BrokenResolver()).check(domain.id)  # type: ignore[arg-type]
    assert rows == [] and db.flush_count == 1


@pytest.mark.asyncio
async def test_analytics_metrics_products_campaigns_and_contact() -> None:
    product_id, campaign_id = uuid4(), uuid4()
    product = SimpleNamespace(
        id=product_id,
        workspace_id=WORKSPACE_ID,
        name="Sites",
        average_check=100_000.0,
        monthly_fee=20_000.0,
    )
    campaign = SimpleNamespace(
        id=campaign_id,
        workspace_id=WORKSPACE_ID,
        name="C1",
        product_id=product_id,
        sent_count=100,
        opened_count=50,
        clicked_count=10,
        replied_count=5,
        bounced_count=2,
        meeting_count=3,
    )
    service = AnalyticsService(FakeDB(), WORKSPACE_ID)  # type: ignore[arg-type]
    service.db.get = AsyncMock(side_effect=[product, campaign])  # type: ignore[method-assign]
    metric = daily(date.today())
    service._metrics = AsyncMock(side_effect=[[metric], []])  # type: ignore[method-assign]
    product_stats = await service.get_product_stats(product_id)
    campaign_stats = await service.get_campaign_stats(campaign_id)
    assert product_stats["estimated_revenue"] == 34_000
    assert campaign_stats["delivery_rate"] == 0.98

    contact = SimpleNamespace(
        id=uuid4(),
        workspace_id=WORKSPACE_ID,
        email="a@example.com",
        status="opened",
        has_replied=True,
        is_unsubscribed=False,
    )
    now = datetime.now(UTC)
    messages = [SimpleNamespace(sent_at=now, opened_at=now, clicked_at=None)]
    db = FakeDB(scalars=[messages], gets=[contact])
    contact_stats = await AnalyticsService(db, WORKSPACE_ID).contact_stats(contact.id)  # type: ignore[arg-type]
    assert contact_stats["sent"] == 1 and contact_stats["replied"] is True


@pytest.mark.asyncio
async def test_analytics_fallback_dashboard_trends_reports() -> None:
    product_id = uuid4()
    product = SimpleNamespace(
        id=product_id,
        workspace_id=WORKSPACE_ID,
        name="Automation",
        average_check=150_000.0,
        monthly_fee=30_000.0,
    )
    campaign = SimpleNamespace(
        sent_count=10,
        bounced_count=1,
        opened_count=5,
        clicked_count=2,
        replied_count=1,
        meeting_count=2,
    )
    db = FakeDB(scalars=[[campaign]], gets=[product])
    service = AnalyticsService(db, WORKSPACE_ID)  # type: ignore[arg-type]
    service._metrics = AsyncMock(return_value=[])  # type: ignore[method-assign]
    stats = await service.get_product_stats(product_id)
    assert stats["sent"] == 10 and stats["estimated_revenue"] == 102_000

    metric_a, metric_b = daily(date.today()), daily(date.today(), 20)
    service._metrics = AsyncMock(return_value=[metric_a, metric_b])  # type: ignore[method-assign]
    trends = await service.trends()
    assert len(trends) == 1 and trends[0]["sent"] == 30

    db = FakeDB(scalars=[[product]])
    service = AnalyticsService(db, WORKSPACE_ID)  # type: ignore[arg-type]
    service.get_product_stats = AsyncMock(return_value={"estimated_revenue": 123})  # type: ignore[method-assign]
    service._metrics = AsyncMock(return_value=[metric_a])  # type: ignore[method-assign]
    dashboard = await service.dashboard()
    assert dashboard["totals"]["estimated_revenue"] == 123

    service.dashboard = AsyncMock(return_value={"ok": True})  # type: ignore[method-assign]
    report = await service.generate_report(GenerateReportRequest(format="json"))
    assert '"ok": true' in report.content
    service.trends = AsyncMock(return_value=[{"date": "2026-01-01", "sent": 1}])  # type: ignore[method-assign]
    csv_report = await service.generate_report(
        GenerateReportRequest(report_type="products", format="csv")
    )
    assert "date,sent" in csv_report.content
    assert AnalyticsService._flatten({"nested": {"a": 1}})["nested"] == '{"a": 1}'


@pytest.mark.asyncio
async def test_analytics_not_found_report_and_aggregate() -> None:
    service = AnalyticsService(FakeDB(gets=[None]), WORKSPACE_ID)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.get_product_stats(uuid4())
    service = AnalyticsService(FakeDB(gets=[None]), WORKSPACE_ID)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.get_campaign_stats(uuid4())
    service = AnalyticsService(FakeDB(gets=[None]), WORKSPACE_ID)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.contact_stats(uuid4())
    service = AnalyticsService(FakeDB(scalar=[None]), WORKSPACE_ID)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.get_report(uuid4())
    report = AnalyticsReport(
        workspace_id=WORKSPACE_ID,
        report_type="dashboard",
        format="json",
        status="completed",
        parameters={},
        content="{}",
    )
    report_service = AnalyticsService(FakeDB(scalar=[report]), WORKSPACE_ID)  # type: ignore[arg-type]
    assert await report_service.get_report(uuid4()) is report

    campaign = SimpleNamespace(id=uuid4(), product_id=uuid4())
    now = datetime.now(UTC)
    contact_id = uuid4()
    message = SimpleNamespace(
        sent_at=now,
        delivered_at=now,
        opened_at=now,
        clicked_at=now,
        bounced=False,
        bounced_at=None,
        contact_id=contact_id,
    )
    contact = SimpleNamespace(has_replied=True, status="meeting_booked")
    db = FakeDB(scalar=[None], scalars=[[campaign], [message], [contact]])
    count = await AnalyticsService(db, WORKSPACE_ID).aggregate_daily(date.today())  # type: ignore[arg-type]
    assert count == 1
    metric = next(row for row in db.added if isinstance(row, DailyMetric))
    assert metric.sent_count == 1 and metric.meeting_count == 1


def test_quality_all_branches() -> None:
    checker = QualityChecker()
    good_text = " ".join(["Расскажите"] + ["слово"] * 55)
    good = checker.check(
        '<p>{{first_name}}</p><a href="https://example.com">link</a><p>unsubscribe</p>',
        good_text,
        "Короткая тема",
    )
    assert good.score == 100 and not good.issues
    long_text = " ".join(["WORD"] * 401)
    bad = checker.check(
        '<p>{{first_name}}</p><img src="x"><p>отписаться</p>',
        long_text + "!!!!! free",
        "X" * 61,
    )
    assert bad.caps_ratio > 0.3
    assert bad.image_count == 1
    assert bad.suggestions
