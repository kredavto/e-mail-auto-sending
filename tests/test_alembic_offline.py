from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CREATE_TABLE = re.compile(
    r"\bCREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(?:\w+\.)?[\"`]?([\w]+)[\"`]?",
    re.IGNORECASE,
)
CREATE_INDEX = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+[\"`]?([\w]+)[\"`]?",
    re.IGNORECASE,
)

PHASE_TABLES = {
    "0001_phase1": {
        "users",
        "auth_sessions",
        "workspaces",
        "workspace_members",
        "workspace_invitations",
        "contacts",
        "segments",
        "uploaded_files",
        "signatures",
        "products",
        "templates",
        "template_versions",
        "portfolio_cases",
        "sequences",
        "sequence_steps",
        "campaigns",
        "campaign_contacts",
        "email_messages",
        "tracking_events",
        "failed_tasks",
    },
    "0002_phase2": {
        "bitrix_sync_logs",
        "linkedin_profiles",
        "linkedin_exports",
        "tenchat_profiles",
        "tenchat_messages",
        "omnichannel_events",
    },
    "0003_phase3": {
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
    },
    "0004_phase4": {
        "notifications",
        "notification_preferences",
        "webpush_subscriptions",
        "enterprise_event_outbox",
        "audit_logs",
        "security_audit_events",
        "audit_exports",
        "webhooks",
        "webhook_deliveries",
        "webhook_outbox",
        "subscriptions",
        "usage_logs",
        "invoices",
        "payment_events",
    },
    "0005_enterprise_delivery": {"notification_deliveries"},
}


def _offline_sql() -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _duplicates(names: list[str]) -> set[str]:
    return {name for name, count in Counter(name.lower() for name in names).items() if count > 1}


def _revision_sections(sql: str) -> dict[str, str]:
    markers = list(re.finditer(r"^-- Running upgrade .*->\s*(000[1-5]_[a-z0-9_]+)\s*$", sql, re.M))
    sections: dict[str, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(sql)
        sections[marker.group(1)] = sql[marker.end() : end]
    return sections


def test_offline_upgrade_has_unique_phase_owned_ddl() -> None:
    """Every table and index must be emitted once, without connecting to a database."""
    sql = _offline_sql()
    tables = CREATE_TABLE.findall(sql)
    indexes = CREATE_INDEX.findall(sql)

    duplicate_tables = _duplicates(tables)
    duplicate_indexes = _duplicates(indexes)
    assert not duplicate_tables, f"duplicate CREATE TABLE names: {sorted(duplicate_tables)}"
    assert not duplicate_indexes, f"duplicate CREATE INDEX names: {sorted(duplicate_indexes)}"

    sections = _revision_sections(sql)
    assert set(sections) == set(PHASE_TABLES)
    for revision, expected_tables in PHASE_TABLES.items():
        assert set(CREATE_TABLE.findall(sections[revision])) == expected_tables

    assert "linkedin_url" not in sections["0001_phase1"]
    assert "delivered_at" not in sections["0001_phase1"]
    assert "meeting_count" not in sections["0001_phase1"]
    assert "linkedin_url" in sections["0002_phase2"]
    assert "delivered_at" in sections["0002_phase2"]
    assert "meeting_count" not in sections["0002_phase2"]
    assert "meeting_count" in sections["0003_phase3"]
    phase4 = sections["0004_phase4"]
    assert "BEFORE TRUNCATE ON audit_logs" in phase4
    assert "BEFORE TRUNCATE ON security_audit_events" in phase4
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM mailer_app" in phase4
    assert "GRANT SELECT, INSERT ON audit_logs, security_audit_events TO mailer_app" in phase4
    assert "CONSTRAINT uq_invoices_workspace_id_idempotency_key" in phase4
    assert "UNIQUE (workspace_id, idempotency_key)" in phase4
    phase5 = sections["0005_enterprise_delivery"]
    assert "CONSTRAINT uq_invoices_provider_payment_identity" in phase5
    assert "UNIQUE (provider, provider_payment_id)" in phase5
    assert "CONSTRAINT uq_invoices_provider_invoice_identity" in phase5
    assert "UNIQUE (provider, provider_invoice_id)" in phase5
    assert "CONSTRAINT uq_notification_deliveries_target" in phase5
    assert "UNIQUE (notification_id, channel, target_id)" in phase5
    assert "ADD COLUMN materialized_at TIMESTAMP WITH TIME ZONE" in phase5


def test_runtime_role_bootstrap_has_no_ddl_or_trigger_bypass() -> None:
    source = (ROOT / "infrastructure" / "postgres" / "init-runtime-role.sh").read_text()
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT" in source
    assert "REVOKE CREATE ON SCHEMA public" in source
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in source
    assert "GRANT USAGE ON SCHEMA public" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES" in source
    assert "ALTER TABLE" not in source
    assert "DISABLE TRIGGER" not in source
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "DATABASE_URL: postgresql+asyncpg://${POSTGRES_RUNTIME_USER" in compose
    assert "MIGRATION_DATABASE_URL: postgresql+asyncpg://${POSTGRES_OWNER_USER" in compose
    assert 'command: ["alembic", "upgrade", "head"]' in compose
    assert 'command: ["uvicorn"' in compose


def test_historical_schema_revisions_do_not_import_current_metadata() -> None:
    for filename in (
        "0001_phase1_schema.py",
        "0003_phase3_analytics_quality.py",
        "0004_phase4_enterprise.py",
    ):
        source = (ROOT / "alembic" / "versions" / filename).read_text()
        assert "Base.metadata" not in source
        assert "from app" not in source
