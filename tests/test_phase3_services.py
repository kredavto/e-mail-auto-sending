from types import SimpleNamespace
from uuid import UUID

import pytest

from app.modules.ab_testing.service import ABTestingService
from app.modules.blacklists.service import BlacklistMonitor
from app.modules.email_validation.service import EmailValidationService, ValidationData
from app.modules.quality.service import QualityChecker
from app.modules.warmup.service import WarmupService


def variant(sent: int, replied: int) -> SimpleNamespace:
    return SimpleNamespace(
        sent_count=sent,
        replied_count=replied,
        opened_count=0,
        clicked_count=0,
        meeting_count=0,
        reply_rate=replied / sent,
        open_rate=0,
        click_rate=0,
        meeting_rate=0,
    )


def test_ab_assignment_is_deterministic_and_respects_extreme_splits() -> None:
    test_id = UUID("00000000-0000-0000-0000-000000000001")
    contact_id = UUID("00000000-0000-0000-0000-000000000002")
    assert ABTestingService.assign_variant(
        test_id, contact_id, 0.5
    ) == ABTestingService.assign_variant(test_id, contact_id, 0.5)
    assert ABTestingService.assign_variant(test_id, contact_id, 0.999) == "A"


def test_ab_analyses_find_clear_winner_and_sample_size() -> None:
    service = ABTestingService()
    a, b = variant(1000, 40), variant(1000, 100)
    frequentist = service.frequentist_analysis(a, b, "reply_rate")
    bayesian = service.bayesian_analysis(a, b)
    assert frequentist["is_significant"] is True
    assert frequentist["winner"] == "B"
    assert bayesian["probability_b_better"] > 0.99
    assert ABTestingService.calculate_required_sample_size(0.05, 0.2) > 0


class NoMxResolver:
    async def resolve(self, _name: str, _kind: str) -> list[object]:
        import dns.resolver

        raise dns.resolver.NXDOMAIN


@pytest.mark.asyncio
async def test_email_validation_checks_syntax_disposable_and_mx() -> None:
    service = EmailValidationService(resolver=NoMxResolver(), providers=[])
    invalid = await service.validate("not-an-email", persist=False)
    disposable = await service.validate("user@mailinator.com", persist=False)
    assert isinstance(invalid, ValidationData) and invalid.status == "invalid"
    assert isinstance(disposable, ValidationData) and disposable.is_disposable
    assert not disposable.has_mx_records


class ListedResolver:
    async def resolve(self, _name: str, _kind: str) -> list[str]:
        return ["127.0.0.2"]


@pytest.mark.asyncio
async def test_blacklist_monitor_queries_every_configured_list() -> None:
    rows = await BlacklistMonitor(ListedResolver()).check_ip("192.0.2.1")
    assert len(rows) == len(BlacklistMonitor.BLACKLISTS)
    assert all(row.listed for row in rows)


def test_warmup_is_compounded_and_capped() -> None:
    plan = SimpleNamespace(target_daily_limit=200, increment_percent=0.2)
    assert WarmupService.limit_on_day(plan, 1) == 20
    assert WarmupService.limit_on_day(plan, 2) == 24
    assert WarmupService.limit_on_day(plan, 100) == 200


def test_quality_checker_reports_hard_requirements() -> None:
    report = QualityChecker().check("<p>БЕСПЛАТНО!!!</p>", "БЕСПЛАТНО!!!", "СРОЧНО!")
    assert report.score < 70
    assert any("персонализировано" in issue for issue in report.issues)
    assert any("отписки" in issue for issue in report.issues)
