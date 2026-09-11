from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.config import Settings
from app.modules.billing.router import usage
from app.modules.billing.service import BillingService, LimitExceededError


def service_for(plan="free", enabled=True, status="active"):
    service = BillingService(Mock(), uuid4(), Settings(_env_file=None, free_plan_test_mode=enabled))
    subscription = SimpleNamespace(
        id=uuid4(), plan=plan, status=status,
        current_period_start=datetime(2026, 9, 1, tzinfo=UTC),
        current_period_end=datetime(2026, 9, 30, tzinfo=UTC),
    )
    service.repo.subscription = AsyncMock(return_value=subscription)
    service.get_or_create_subscription = AsyncMock(return_value=subscription)
    service.current_usage = AsyncMock(return_value=1000000)
    return service


@pytest.mark.parametrize(
    "action", ["create_contact", "send_email", "add_domain", "add_user", "api_call"]
)
async def test_free_testing_opens_all_quota_actions(action):
    service = service_for()
    assert await service.check_limits(action, 70000)
    service.current_usage.assert_not_awaited()
    assert service.repo.subscription.return_value.plan == "free"


@pytest.mark.parametrize("plan", ["free", "pro", "business"])
async def test_normal_limits_return_and_paid_plans_are_unchanged(plan):
    service = service_for(plan=plan, enabled=plan != "free")
    with pytest.raises(LimitExceededError):
        await service.check_limits("create_contact", 500)


async def test_turning_mode_off_restores_original_limits_without_mutation():
    service = service_for()
    assert all(value is None for value in service.effective_limits("free").values())
    service.settings.free_plan_test_mode = False
    assert service.effective_limits("free") == {
        "emails_per_month": 500, "contacts": 100, "domains": 1, "users": 1,
    }
    with pytest.raises(LimitExceededError):
        await service.check_limits("create_contact")


async def test_mode_keeps_subscription_and_input_guards():
    with pytest.raises(LimitExceededError, match="неактивна"):
        await service_for(status="past_due").check_limits("send_email")
    with pytest.raises(ValueError):
        await service_for().check_limits("unknown")
    with pytest.raises(ValueError):
        await service_for().check_limits("send_email", 0)


@pytest.mark.parametrize("enabled", [False, True])
async def test_usage_reports_effective_limits_and_keeps_actual_counts(enabled):
    service = service_for(enabled=enabled)
    with patch("app.modules.billing.router.BillingService", return_value=service):
        report = await usage(SimpleNamespace(workspace_id=service.workspace_id), Mock())
    assert report.plan == "free" and report.free_plan_test_mode is enabled
    assert all(item.count == 1000000 for item in report.items)
    if enabled:
        assert all(item.limit is None and item.percent is None for item in report.items)
    else:
        assert [item.limit for item in report.items] == [500, 100, 1, 1]


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FREE_PLAN_TEST_MODE", raising=False)
    assert Settings(_env_file=None).free_plan_test_mode is False
