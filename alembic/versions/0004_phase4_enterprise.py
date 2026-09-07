"""Phase 4 enterprise notifications, audit, webhooks and billing.

Revision ID: 0004_phase4
Revises: 0003_phase3
"""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_phase4"
down_revision = "0003_phase3"
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


def _create_table(name: str, *columns: Any, timestamps: bool = True) -> None:
    op.create_table(
        name,
        _id(),
        *columns,
        *(_timestamps() if timestamps else []),
        sa.PrimaryKeyConstraint("id", name=f"pk_{name}"),
    )


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def _workspace_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id"],
        ["workspaces.id"],
        name=f"fk_{table}_workspace_id_workspaces",
        ondelete="CASCADE",
    )


def upgrade() -> None:
    _create_table(
        "notifications",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("channel", sa.String(20), server_default="in_app", nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_notifications_user_id_users", ondelete="CASCADE"
        ),
        _workspace_fk("notifications"),
        timestamps=False,
    )
    for column in ("user_id", "workspace_id", "type", "is_read", "created_at"):
        _index("notifications", column)

    _create_table(
        "notification_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_notifications", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("webpush_notifications", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "telegram_notifications", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        sa.Column("telegram_chat_id", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_notification_preferences_user_id_users",
            ondelete="CASCADE",
        ),
        _workspace_fk("notification_preferences"),
        sa.UniqueConstraint("user_id", "workspace_id", name="uq_notification_preferences_user_id"),
    )
    _index("notification_preferences", "user_id")
    _index("notification_preferences", "workspace_id")

    _create_table(
        "webpush_subscriptions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_webpush_subscriptions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("endpoint", name="uq_webpush_subscriptions_endpoint"),
    )
    _index("webpush_subscriptions", "user_id")

    _create_table(
        "enterprise_event_outbox",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _workspace_fk("enterprise_event_outbox"),
        sa.UniqueConstraint("event_id", name="uq_enterprise_event_outbox_event_id"),
        timestamps=False,
    )
    for column in ("workspace_id", "event_type", "created_at"):
        _index("enterprise_event_outbox", column)

    _create_table(
        "audit_logs",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("old_values", postgresql.JSONB(), nullable=True),
        sa.Column("new_values", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_audit_logs_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_audit_logs_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        timestamps=False,
    )
    for column in (
        "workspace_id",
        "user_id",
        "action",
        "resource_type",
        "resource_id",
        "request_id",
        "created_at",
    ):
        _index("audit_logs", column)
    op.execute("""
        CREATE FUNCTION prevent_audit_log_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs are immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """)
    op.execute("""
        CREATE TRIGGER trg_audit_logs_immutable
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation()
        """)
    op.execute("""
        CREATE TRIGGER trg_audit_logs_no_truncate
        BEFORE TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_audit_log_mutation()
        """)

    _create_table(
        "security_audit_events",
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email_hash", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_security_audit_events_user_id_users",
            ondelete="RESTRICT",
        ),
        timestamps=False,
    )
    for column in ("event_type", "user_id", "email_hash", "created_at"):
        _index("security_audit_events", column)
    op.execute("""
        CREATE TRIGGER trg_security_audit_events_immutable
        BEFORE UPDATE OR DELETE ON security_audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation()
        """)
    op.execute("""
        CREATE TRIGGER trg_security_audit_events_no_truncate
        BEFORE TRUNCATE ON security_audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_audit_log_mutation()
        """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mailer_app') THEN
                REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM mailer_app;
                REVOKE UPDATE, DELETE, TRUNCATE ON security_audit_events FROM mailer_app;
                GRANT SELECT, INSERT ON audit_logs, security_audit_events TO mailer_app;
            END IF;
        END
        $$
        """)

    _create_table(
        "audit_exports",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("filters", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_audit_exports_user_id_users", ondelete="CASCADE"
        ),
        _workspace_fk("audit_exports"),
        timestamps=False,
    )
    _index("audit_exports", "workspace_id")
    _index("audit_exports", "user_id")

    _create_table(
        "webhooks",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("events", postgresql.JSONB(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _workspace_fk("webhooks"),
    )
    _index("webhooks", "workspace_id")
    _index("webhooks", "is_active")

    _create_table(
        "webhook_deliveries",
        sa.Column("webhook_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("success", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["webhook_id"],
            ["webhooks.id"],
            name="fk_webhook_deliveries_webhook_id_webhooks",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("webhook_id", "event_id", name="uq_webhook_deliveries_webhook_id"),
        timestamps=False,
    )
    for column in ("webhook_id", "event_id", "event_type", "success"):
        _index("webhook_deliveries", column)

    _create_table(
        "webhook_outbox",
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["webhook_deliveries.id"],
            name="fk_webhook_outbox_delivery_id_webhook_deliveries",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("delivery_id", name="uq_webhook_outbox_delivery_id"),
        timestamps=False,
    )
    _index("webhook_outbox", "delivery_id")
    _index("webhook_outbox", "created_at")

    _create_table(
        "subscriptions",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan", sa.String(20), server_default="free", nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("provider", sa.String(20), nullable=True),
        sa.Column("provider_subscription_id", sa.String(255), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_at", sa.DateTime(timezone=True), nullable=True),
        _workspace_fk("subscriptions"),
        sa.UniqueConstraint("workspace_id", name="uq_subscriptions_workspace_id"),
        sa.UniqueConstraint(
            "provider_subscription_id", name="uq_subscriptions_provider_subscription_id"
        ),
    )
    for column in ("plan", "status", "provider_subscription_id"):
        _index("subscriptions", column)

    _create_table(
        "usage_logs",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric", sa.String(50), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        _workspace_fk("usage_logs"),
        sa.UniqueConstraint(
            "workspace_id", "metric", "period_start", name="uq_usage_logs_workspace_id"
        ),
    )
    _index("usage_logs", "workspace_id")
    _index("usage_logs", "metric")

    _create_table(
        "invoices",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(20), nullable=True),
        sa.Column("provider_payment_id", sa.String(255), nullable=True),
        sa.Column("provider_invoice_id", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("plan", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), server_default="initial", nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="RUB", nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_url", sa.String(500), nullable=True),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        _workspace_fk("invoices"),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name="fk_invoices_subscription_id_subscriptions",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("provider_invoice_id", name="uq_invoices_provider_invoice_id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_invoices_workspace_id_idempotency_key"
        ),
    )
    for column in ("workspace_id", "provider_payment_id", "status"):
        _index("invoices", column)

    _create_table(
        "payment_events",
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("provider", "external_event_id", name="uq_payment_events_provider"),
        timestamps=False,
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_security_audit_events_no_truncate " "ON security_audit_events"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_security_audit_events_immutable ON security_audit_events"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_no_truncate ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs")
    for table in (
        "payment_events",
        "invoices",
        "usage_logs",
        "subscriptions",
        "webhook_outbox",
        "webhook_deliveries",
        "webhooks",
        "audit_exports",
        "security_audit_events",
        "audit_logs",
        "enterprise_event_outbox",
        "webpush_subscriptions",
        "notification_preferences",
        "notifications",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()")
