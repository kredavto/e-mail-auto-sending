"""Static Phase 3 analytics, data quality and deliverability schema.

Revision ID: 0003_phase3
Revises: 0002_phase2
"""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_phase3"
down_revision = "0002_phase2"
branch_labels = None
depends_on = None


def _id() -> sa.Column[object]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False)


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _create_table(name: str, *columns: Any) -> None:
    op.create_table(
        name,
        _id(),
        *columns,
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=f"pk_{name}"),
    )


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("meeting_count", sa.Integer(), server_default="0", nullable=False),
    )

    _create_table(
        "ab_tests",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("test_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("split_ratio", sa.Float(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("confidence_level", sa.Float(), nullable=False),
        sa.Column("primary_metric", sa.String(30), nullable=False),
        sa.Column("min_detectable_effect", sa.Float(), nullable=False),
        sa.Column("winner_variant", sa.String(1), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_ab_tests_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_ab_tests_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
    )
    for column in ("workspace_id", "campaign_id", "status"):
        _index("ab_tests", column)

    _create_table(
        "ab_test_variants",
        sa.Column("test_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_key", sa.String(1), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("sender_name", sa.String(100), nullable=True),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("opened_count", sa.Integer(), nullable=False),
        sa.Column("replied_count", sa.Integer(), nullable=False),
        sa.Column("clicked_count", sa.Integer(), nullable=False),
        sa.Column("meeting_count", sa.Integer(), nullable=False),
        sa.Column("open_rate", sa.Float(), nullable=False),
        sa.Column("reply_rate", sa.Float(), nullable=False),
        sa.Column("click_rate", sa.Float(), nullable=False),
        sa.Column("meeting_rate", sa.Float(), nullable=False),
        sa.Column("p_value", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["ab_tests.id"],
            name="fk_ab_test_variants_test_id_ab_tests",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            name="fk_ab_test_variants_template_id_templates",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("test_id", "variant_key", name="uq_ab_test_variants_test_id"),
    )
    _index("ab_test_variants", "test_id")

    _create_table(
        "ab_test_assignments",
        sa.Column("test_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_key", sa.String(1), nullable=False),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["ab_tests.id"],
            name="fk_ab_test_assignments_test_id_ab_tests",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name="fk_ab_test_assignments_contact_id_contacts",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("test_id", "contact_id", name="uq_ab_test_assignments_test_id"),
    )
    _index("ab_test_assignments", "test_id")
    _index("ab_test_assignments", "contact_id")

    _create_table(
        "email_validation_results",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("is_disposable", sa.Boolean(), nullable=False),
        sa.Column("is_role_based", sa.Boolean(), nullable=False),
        sa.Column("has_mx_records", sa.Boolean(), nullable=False),
        sa.Column("smtp_check_passed", sa.Boolean(), nullable=False),
        sa.Column("is_spam_trap", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_email_validation_results_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id", "email", name="uq_email_validation_results_workspace_id"
        ),
    )
    for column in ("workspace_id", "email", "status"):
        _index("email_validation_results", column)

    _create_table(
        "enrichment_results",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("source", sa.String(30), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("enriched_data", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_enrichment_results_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name="fk_enrichment_results_contact_id_contacts",
            ondelete="CASCADE",
        ),
    )
    _index("enrichment_results", "workspace_id")
    _index("enrichment_results", "contact_id")

    _create_table(
        "daily_metrics",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("delivered_count", sa.Integer(), nullable=False),
        sa.Column("opened_count", sa.Integer(), nullable=False),
        sa.Column("clicked_count", sa.Integer(), nullable=False),
        sa.Column("replied_count", sa.Integer(), nullable=False),
        sa.Column("bounced_count", sa.Integer(), nullable=False),
        sa.Column("meeting_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_daily_metrics_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_daily_metrics_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_daily_metrics_product_id_products",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("campaign_id", "date", name="uq_daily_metrics_campaign_id"),
    )
    for column in ("workspace_id", "campaign_id", "product_id", "date"):
        _index("daily_metrics", column)

    _create_table(
        "analytics_reports",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_type", sa.String(30), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_analytics_reports_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
    )
    _index("analytics_reports", "workspace_id")

    _create_table(
        "sending_domains",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dkim_enabled", sa.Boolean(), nullable=False),
        sa.Column("dkim_records", postgresql.JSONB(), nullable=False),
        sa.Column("spf_record", sa.Text(), nullable=True),
        sa.Column("dmarc_record", sa.Text(), nullable=True),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("current_daily_count", sa.Integer(), nullable=False),
        sa.Column("daily_count_date", sa.Date(), nullable=True),
        sa.Column("reputation_score", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_sending_domains_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("workspace_id", "domain", name="uq_sending_domains_workspace_id"),
    )
    for column in ("workspace_id", "domain", "status"):
        _index("sending_domains", column)

    _create_table(
        "domain_verifications",
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("spf_present", sa.Boolean(), nullable=False),
        sa.Column("dkim_valid", sa.Boolean(), nullable=False),
        sa.Column("dmarc_present", sa.Boolean(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["sending_domains.id"],
            name="fk_domain_verifications_domain_id_sending_domains",
            ondelete="CASCADE",
        ),
    )
    _index("domain_verifications", "domain_id")

    _create_table(
        "warmup_plans",
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("current_daily_limit", sa.Integer(), nullable=False),
        sa.Column("target_daily_limit", sa.Integer(), nullable=False),
        sa.Column("increment_percent", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["sending_domains.id"],
            name="fk_warmup_plans_domain_id_sending_domains",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("domain_id", name="uq_warmup_plans_domain_id"),
    )
    _index("warmup_plans", "domain_id")
    _index("warmup_plans", "status")

    _create_table(
        "blacklist_checks",
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("blacklist", sa.String(50), nullable=False),
        sa.Column("listed", sa.Boolean(), nullable=False),
        sa.Column("return_code", sa.String(100), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["sending_domains.id"],
            name="fk_blacklist_checks_domain_id_sending_domains",
            ondelete="CASCADE",
        ),
    )
    for column in ("domain_id", "ip_address", "blacklist", "listed"):
        _index("blacklist_checks", column)

    _create_table(
        "blacklist_subscriptions",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_email", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_blacklist_subscriptions_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["sending_domains.id"],
            name="fk_blacklist_subscriptions_domain_id_sending_domains",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "domain_id",
            "notification_email",
            name="uq_blacklist_subscriptions_domain_id",
        ),
    )
    _index("blacklist_subscriptions", "workspace_id")
    _index("blacklist_subscriptions", "domain_id")

    _create_table(
        "blacklist_alerts",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blacklist", sa.String(50), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_blacklist_alerts_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["sending_domains.id"],
            name="fk_blacklist_alerts_domain_id_sending_domains",
            ondelete="CASCADE",
        ),
    )
    _index("blacklist_alerts", "workspace_id")
    _index("blacklist_alerts", "domain_id")
    _index("blacklist_alerts", "acknowledged")


def downgrade() -> None:
    for table in (
        "blacklist_alerts",
        "blacklist_subscriptions",
        "blacklist_checks",
        "warmup_plans",
        "domain_verifications",
        "sending_domains",
        "analytics_reports",
        "daily_metrics",
        "enrichment_results",
        "email_validation_results",
        "ab_test_assignments",
        "ab_test_variants",
        "ab_tests",
    ):
        op.drop_table(table)
    op.drop_column("campaigns", "meeting_count")
