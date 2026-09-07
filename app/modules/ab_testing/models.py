from uuid import UUID

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class ABTest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ab_tests"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    test_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    split_ratio: Mapped[float] = mapped_column(Float, default=0.5)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    confidence_level: Mapped[float] = mapped_column(Float, default=0.95)
    primary_metric: Mapped[str] = mapped_column(String(30), default="reply_rate")
    min_detectable_effect: Mapped[float] = mapped_column(Float, default=0.1)
    winner_variant: Mapped[str | None] = mapped_column(String(1), nullable=True)


class ABTestVariant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ab_test_variants"

    test_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ab_tests.id", ondelete="CASCADE"), index=True
    )
    variant_key: Mapped[str] = mapped_column(String(1))
    template_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    opened_count: Mapped[int] = mapped_column(Integer, default=0)
    replied_count: Mapped[int] = mapped_column(Integer, default=0)
    clicked_count: Mapped[int] = mapped_column(Integer, default=0)
    meeting_count: Mapped[int] = mapped_column(Integer, default=0)
    open_rate: Mapped[float] = mapped_column(Float, default=0)
    reply_rate: Mapped[float] = mapped_column(Float, default=0)
    click_rate: Mapped[float] = mapped_column(Float, default=0)
    meeting_rate: Mapped[float] = mapped_column(Float, default=0)
    p_value: Mapped[float] = mapped_column(Float, default=1)
    __table_args__ = (UniqueConstraint("test_id", "variant_key"),)


class ABTestAssignment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ab_test_assignments"

    test_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ab_tests.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    variant_key: Mapped[str] = mapped_column(String(1))
    __table_args__ = (UniqueConstraint("test_id", "contact_id"),)
