from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class SendingDomain(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sending_domains"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    domain: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    dkim_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    dkim_records: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    spf_record: Mapped[str | None] = mapped_column(Text, nullable=True)
    dmarc_record: Mapped[str | None] = mapped_column(Text, nullable=True)
    daily_limit: Mapped[int] = mapped_column(Integer, default=200)
    current_daily_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_count_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reputation_score: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("workspace_id", "domain"),)


class DomainVerification(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "domain_verifications"

    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sending_domains.id", ondelete="CASCADE"), index=True
    )
    spf_present: Mapped[bool] = mapped_column(Boolean, default=False)
    dkim_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    dmarc_present: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
