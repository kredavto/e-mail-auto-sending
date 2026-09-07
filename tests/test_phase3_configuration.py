import app.models  # noqa: F401
from app.celery_app import celery_app
from app.database import Base
from app.main import create_app


def test_phase3_models_registered() -> None:
    expected = {
        "ab_tests",
        "ab_test_variants",
        "ab_test_assignments",
        "email_validation_results",
        "enrichment_results",
        "daily_metrics",
        "analytics_reports",
        "sending_domains",
        "domain_verifications",
        "warmup_plans",
        "blacklist_checks",
        "blacklist_subscriptions",
        "blacklist_alerts",
    }
    assert expected <= set(Base.metadata.tables)


def test_phase3_routes_registered() -> None:
    paths = create_app().openapi()["paths"]
    expected = {
        "/api/v1/ab-tests",
        "/api/v1/validation/validate",
        "/api/v1/enrichment/enrich/{contact_id}",
        "/api/v1/analytics/dashboard",
        "/api/v1/domains",
        "/api/v1/warmup/start",
        "/api/v1/blacklists/check",
        "/api/v1/quality/check",
    }
    assert expected <= set(paths)


def test_phase3_celery_schedule_registered() -> None:
    for module in (
        "app.modules.ab_testing.tasks",
        "app.modules.email_validation.tasks",
        "app.modules.enrichment.tasks",
        "app.modules.analytics.tasks",
        "app.modules.warmup.tasks",
        "app.modules.blacklists.tasks",
    ):
        assert module in celery_app.conf.include
    for schedule in ("update-ab-test-metrics", "aggregate-daily-analytics", "check-blacklists"):
        assert schedule in celery_app.conf.beat_schedule
