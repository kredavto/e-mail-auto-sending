from datetime import date
from uuid import UUID

from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class WarmupPlan(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "warmup_plans"

    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sending_domains.id", ondelete="CASCADE"), index=True
    )
    start_date: Mapped[date] = mapped_column(Date)
    current_daily_limit: Mapped[int] = mapped_column(Integer, default=20)
    target_daily_limit: Mapped[int] = mapped_column(Integer)
    increment_percent: Mapped[float] = mapped_column(Float, default=0.2)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    provider: Mapped[str] = mapped_column(String(30), default="internal")
    __table_args__ = (UniqueConstraint("domain_id"),)
