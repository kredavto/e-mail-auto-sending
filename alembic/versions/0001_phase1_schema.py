"""Static and reproducible Phase 1 schema snapshot.

Revision ID: 0001_phase1

Historical migrations must never import the application's current metadata.
"""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_phase1"
down_revision = None
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


def _index(table: str, column: str, *, unique: bool = False) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column], unique=unique)


def upgrade() -> None:
    _create_table(
        "users",
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False),
        sa.Column("mfa_secret", sa.String(64), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    _index("users", "email", unique=True)

    _create_table(
        "auth_sessions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_auth_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("refresh_token_hash", name="uq_auth_sessions_refresh_token_hash"),
    )
    _index("auth_sessions", "user_id")
    _index("auth_sessions", "family_id")

    _create_table(
        "workspaces",
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_workspaces_owner_id_users"),
    )
    _index("workspaces", "slug", unique=True)
    _index("workspaces", "owner_id")

    _create_table(
        "workspace_members",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_workspace_members_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_workspace_members_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_id"),
    )
    _index("workspace_members", "workspace_id")
    _index("workspace_members", "user_id")

    _create_table(
        "workspace_invitations",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_workspace_invitations_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invitations_token_hash"),
    )
    _index("workspace_invitations", "workspace_id")
    _index("workspace_invitations", "email")

    _create_table(
        "contacts",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("patronymic", sa.String(100), nullable=True),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("position", sa.String(100), nullable=False),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("current_site_url", sa.String(255), nullable=True),
        sa.Column("company_size", sa.String(50), nullable=True),
        sa.Column("annual_revenue_tier", sa.String(50), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("custom_fields", postgresql.JSONB(), nullable=False),
        sa.Column("has_replied", sa.Boolean(), nullable=False),
        sa.Column("is_unsubscribed", sa.Boolean(), nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_contacts_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("workspace_id", "email", name="uq_contacts_workspace_id"),
    )
    for column in ("workspace_id", "email", "industry", "status"):
        _index("contacts", column)

    _create_table(
        "segments",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_segments_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
    )
    _index("segments", "workspace_id")

    _create_table(
        "uploaded_files",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_uploaded_files_workspace_id_workspaces"
        ),
        sa.UniqueConstraint("storage_key", name="uq_uploaded_files_storage_key"),
    )
    _index("uploaded_files", "workspace_id")

    _create_table(
        "signatures",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("html_template", sa.Text(), nullable=False),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("photo_url", sa.String(500), nullable=True),
        sa.Column("social_links", postgresql.JSONB(), nullable=False),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_signatures_workspace_id_workspaces"
        ),
    )
    _index("signatures", "workspace_id")

    # These columns reference tables created below. The original Phase 1
    # models used named use_alter constraints, so add those constraints later.
    _create_table(
        "products",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("average_check", sa.Float(), nullable=False),
        sa.Column("monthly_fee", sa.Float(), nullable=False),
        sa.Column("setup_fee", sa.Float(), nullable=False),
        sa.Column("target_audience", postgresql.JSONB(), nullable=False),
        sa.Column("buyer_personas", postgresql.JSONB(), nullable=False),
        sa.Column("default_sequence_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("default_template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_products_workspace_id_workspaces"
        ),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_products_workspace_id"),
    )
    _index("products", "workspace_id")
    _index("products", "slug")

    _create_table(
        "templates",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("subject_template", sa.String(255), nullable=False),
        sa.Column("editor_state", postgresql.JSONB(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("signature_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("variables", postgresql.JSONB(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_templates_workspace_id_workspaces"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_templates_product_id_products"
        ),
        sa.ForeignKeyConstraint(
            ["signature_id"], ["signatures.id"], name="fk_templates_signature_id_signatures"
        ),
    )
    _index("templates", "workspace_id")
    _index("templates", "product_id")

    _create_table(
        "template_versions",
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("subject_template", sa.String(255), nullable=False),
        sa.Column("editor_state", postgresql.JSONB(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("variables", postgresql.JSONB(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            name="fk_template_versions_template_id_templates",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("template_id", "version", name="uq_template_versions_template_id"),
    )
    _index("template_versions", "template_id")

    _create_table(
        "portfolio_cases",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("company_size", sa.String(50), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_portfolio_cases_workspace_id_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_portfolio_cases_product_id_products"
        ),
    )
    _index("portfolio_cases", "workspace_id")
    _index("portfolio_cases", "product_id")

    _create_table(
        "sequences",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("stop_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("send_window", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_sequences_workspace_id_workspaces"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_sequences_product_id_products"
        ),
    )
    _index("sequences", "workspace_id")
    _index("sequences", "product_id")

    _create_table(
        "sequence_steps",
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(30), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delay_days", sa.Integer(), nullable=False),
        sa.Column("send_hour", sa.Integer(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["sequence_id"],
            ["sequences.id"],
            name="fk_sequence_steps_sequence_id_sequences",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["templates.id"], name="fk_sequence_steps_template_id_templates"
        ),
    )
    _index("sequence_steps", "sequence_id")

    op.create_foreign_key(
        "fk_products_default_sequence",
        "products",
        "sequences",
        ["default_sequence_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_products_default_template",
        "products",
        "templates",
        ["default_template_id"],
        ["id"],
    )

    _create_table(
        "campaigns",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sequence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_email", sa.String(255), nullable=False),
        sa.Column("sender_name", sa.String(100), nullable=False),
        sa.Column("schedule_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("opened_count", sa.Integer(), nullable=False),
        sa.Column("clicked_count", sa.Integer(), nullable=False),
        sa.Column("replied_count", sa.Integer(), nullable=False),
        sa.Column("bounced_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_campaigns_workspace_id_workspaces"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_campaigns_product_id_products"
        ),
        sa.ForeignKeyConstraint(
            ["sequence_id"], ["sequences.id"], name="fk_campaigns_sequence_id_sequences"
        ),
    )
    for column in ("workspace_id", "product_id", "sequence_id", "status"):
        _index("campaigns", column)

    _create_table(
        "campaign_contacts",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.Column("next_send_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_campaign_contacts_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name="fk_campaign_contacts_contact_id_contacts",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("campaign_id", "contact_id", name="uq_campaign_contacts_campaign_id"),
    )
    for column in ("campaign_id", "contact_id", "next_send_at"):
        _index("campaign_contacts", column)

    _create_table(
        "email_messages",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_email_messages_workspace_id_workspaces"
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], name="fk_email_messages_campaign_id_campaigns"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name="fk_email_messages_contact_id_contacts"
        ),
    )
    for column in ("workspace_id", "campaign_id", "contact_id", "recipient_email", "status"):
        _index("email_messages", column)

    _create_table(
        "tracking_events",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["email_messages.id"],
            name="fk_tracking_events_message_id_email_messages",
            ondelete="CASCADE",
        ),
    )
    _index("tracking_events", "message_id")
    _index("tracking_events", "event_type")

    _create_table(
        "failed_tasks",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_name", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_failed_tasks_workspace_id_workspaces"
        ),
    )
    _index("failed_tasks", "workspace_id")
    _index("failed_tasks", "task_name")


def downgrade() -> None:
    op.drop_constraint("fk_products_default_template", "products", type_="foreignkey")
    op.drop_constraint("fk_products_default_sequence", "products", type_="foreignkey")
    for table in (
        "failed_tasks",
        "tracking_events",
        "email_messages",
        "campaign_contacts",
        "campaigns",
        "sequence_steps",
        "sequences",
        "portfolio_cases",
        "template_versions",
        "templates",
        "products",
        "signatures",
        "uploaded_files",
        "segments",
        "contacts",
        "workspace_invitations",
        "workspace_members",
        "workspaces",
        "auth_sessions",
        "users",
    ):
        op.drop_table(table)
