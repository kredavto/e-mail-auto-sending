from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class EmailValidationResult(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "email_validation_results"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="unknown", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    is_disposable: Mapped[bool] = mapped_column(Boolean, default=False)
    is_role_based: Mapped[bool] = mapped_column(Boolean, default=False)
    has_mx_records: Mapped[bool] = mapped_column(Boolean, default=False)
    smtp_check_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_spam_trap: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(30), default="internal")
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint("workspace_id", "email"),)
