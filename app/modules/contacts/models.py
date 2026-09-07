from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class Contact(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "contacts"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    last_name: Mapped[str] = mapped_column(String(100), default="")
    first_name: Mapped[str] = mapped_column(String(100), default="")
    patronymic: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[str] = mapped_column(String(100), default="Директор")
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    current_site_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    annual_revenue_tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    custom_fields: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    has_replied: Mapped[bool] = mapped_column(Boolean, default=False)
    is_unsubscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    current_step_index: Mapped[int] = mapped_column(default=0)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tenchat_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    bitrix_lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    bitrix_contact_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    bitrix_company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    bitrix_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    __table_args__ = (UniqueConstraint("workspace_id", "email"),)


class Segment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "segments"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    filters: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
