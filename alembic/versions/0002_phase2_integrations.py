"""Phase 2 external integrations.

Revision ID: 0002_phase2
Revises: 0001_phase1
"""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_phase2"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _add_column(table_name: str, column: sa.Column[object]) -> None:
    op.add_column(table_name, column, if_not_exists=True)


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    op.create_index(name, table_name, columns, if_not_exists=True)


def _create_table(name: str, *columns: Any) -> None:
    op.create_table(name, *columns, if_not_exists=True)


def upgrade() -> None:
    _add_column("contacts", sa.Column("linkedin_url", sa.String(500), nullable=True))
    _add_column("contacts", sa.Column("tenchat_user_id", sa.String(100), nullable=True))
    _add_column("contacts", sa.Column("bitrix_lead_id", sa.Integer(), nullable=True))
    _add_column("contacts", sa.Column("bitrix_contact_id", sa.Integer(), nullable=True))
    _add_column("contacts", sa.Column("bitrix_company_id", sa.Integer(), nullable=True))
    _add_column(
        "contacts", sa.Column("bitrix_synced_at", sa.DateTime(timezone=True), nullable=True)
    )
    _create_index("ix_contacts_tenchat_user_id", "contacts", ["tenchat_user_id"])
    _create_index("ix_contacts_bitrix_lead_id", "contacts", ["bitrix_lead_id"])
    _create_index("ix_contacts_bitrix_contact_id", "contacts", ["bitrix_contact_id"])
    _create_index("ix_contacts_bitrix_company_id", "contacts", ["bitrix_company_id"])

    _add_column(
        "email_messages", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_column(
        "email_messages", sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_column(
        "email_messages", sa.Column("complained_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_column("email_messages", sa.Column("bounce_type", sa.String(30), nullable=True))
    _add_column(
        "email_messages",
        sa.Column("bounced", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    _create_table(
        "bitrix_sync_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "contact_id", "entity_type", "entity_id", "status"):
        _create_index(f"ix_bitrix_sync_logs_{column}", "bitrix_sync_logs", [column])

    _create_table(
        "linkedin_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("linkedin_id", sa.String(100), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("headline", sa.String(255), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("company_domain", sa.String(255), nullable=True),
        sa.Column("industry", sa.String(100), nullable=False),
        sa.Column("location", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("email_confidence", sa.Integer(), nullable=True),
        sa.Column("profile_url", sa.String(500), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "linkedin_id"),
    )
    for column in ("workspace_id", "contact_id", "linkedin_id", "email"):
        _create_index(f"ix_linkedin_profiles_{column}", "linkedin_profiles", [column])

    _create_table(
        "linkedin_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("imported_rows", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("ix_linkedin_exports_workspace_id", "linkedin_exports", ["workspace_id"])
    _create_index("ix_linkedin_exports_status", "linkedin_exports", ["status"])

    _create_table(
        "tenchat_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenchat_user_id", sa.String(100), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("position", sa.String(255), nullable=False),
        sa.Column("industry", sa.String(100), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "tenchat_user_id"),
    )
    for column in ("workspace_id", "contact_id", "tenchat_user_id", "email"):
        _create_index(f"ix_tenchat_profiles_{column}", "tenchat_profiles", [column])

    _create_table(
        "tenchat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_message_id", sa.String(150), nullable=True),
        sa.Column("conversation_id", sa.String(150), nullable=True),
        sa.Column("direction", sa.String(1), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_reply", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["tenchat_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "external_message_id"),
    )
    for column in (
        "workspace_id",
        "profile_id",
        "contact_id",
        "external_message_id",
        "conversation_id",
        "direction",
    ):
        _create_index(f"ix_tenchat_messages_{column}", "tenchat_messages", [column])

    _create_table(
        "omnichannel_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_channel", sa.String(30), nullable=False),
        sa.Column("actual_channel", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(100), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sequence_step_id"], ["sequence_steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "contact_id", "actual_channel", "status"):
        _create_index(f"ix_omnichannel_events_{column}", "omnichannel_events", [column])


def downgrade() -> None:
    op.drop_table("omnichannel_events")
    op.drop_table("tenchat_messages")
    op.drop_table("tenchat_profiles")
    op.drop_table("linkedin_exports")
    op.drop_table("linkedin_profiles")
    op.drop_table("bitrix_sync_logs")
    for column in ("bounced", "bounce_type", "complained_at", "bounced_at", "delivered_at"):
        op.drop_column("email_messages", column)
    for column in ("bitrix_company_id", "bitrix_contact_id", "bitrix_lead_id", "tenchat_user_id"):
        op.drop_index(f"ix_contacts_{column}", table_name="contacts")
    for column in (
        "bitrix_synced_at",
        "bitrix_company_id",
        "bitrix_contact_id",
        "bitrix_lead_id",
        "tenchat_user_id",
        "linkedin_url",
    ):
        op.drop_column("contacts", column)
