from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class AssistantRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "assistant_runs"

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    action_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
