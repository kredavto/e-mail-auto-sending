"""Persist tenant-scoped assistant generations and approval receipts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_assistant"
down_revision = "0005_enterprise_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_runs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("action_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_assistant_runs_workspace_id", "assistant_runs", ["workspace_id"])
    op.create_index("ix_assistant_runs_user_id", "assistant_runs", ["user_id"])


def downgrade() -> None:
    op.drop_table("assistant_runs")
