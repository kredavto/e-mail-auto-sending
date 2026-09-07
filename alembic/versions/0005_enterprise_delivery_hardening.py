"""Tenant-safe billing identities and durable notification channel delivery.

Revision ID: 0005_enterprise_delivery
Revises: 0004_phase4
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_enterprise_delivery"
down_revision = "0004_phase4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_invoices_provider_invoice_id", "invoices", type_="unique")
    op.create_unique_constraint(
        "uq_invoices_provider_payment_identity",
        "invoices",
        ["provider", "provider_payment_id"],
    )

    op.add_column(
        "enterprise_event_outbox",
        sa.Column("materialized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_invoices_provider_invoice_identity",
        "invoices",
        ["provider", "provider_invoice_id"],
    )

    op.add_column(
        "notifications",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_notifications_event_id", "notifications", ["event_id"])
    op.create_unique_constraint(
        "uq_notifications_workspace_user_event",
        "notifications",
        ["workspace_id", "user_id", "event_id"],
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(255), server_default="", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name="fk_notification_deliveries_notification_id_notifications",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_deliveries"),
        sa.UniqueConstraint(
            "notification_id",
            "channel",
            "target_id",
            name="uq_notification_deliveries_target",
        ),
    )
    for column in ("notification_id", "channel", "status", "created_at"):
        op.create_index(f"ix_notification_deliveries_{column}", "notification_deliveries", [column])


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_constraint("uq_notifications_workspace_user_event", "notifications", type_="unique")
    op.drop_index("ix_notifications_event_id", table_name="notifications")
    op.drop_column("notifications", "event_id")
    op.drop_column("enterprise_event_outbox", "materialized_at")
    op.drop_constraint("uq_invoices_provider_invoice_identity", "invoices", type_="unique")
    op.drop_constraint("uq_invoices_provider_payment_identity", "invoices", type_="unique")
    op.create_unique_constraint(
        "uq_invoices_provider_invoice_id", "invoices", ["provider_invoice_id"]
    )
