from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class Sequence(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sequences"
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), index=True
    )
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    stop_conditions: Mapped[dict[str, bool]] = mapped_column(
        JSONB,
        default=lambda: {
            "replied": True,
            "unsubscribed": True,
            "bounced": True,
            "meeting_booked": True,
        },
    )
    send_window: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=lambda: {
            "days": ["mon", "tue", "wed", "thu", "fri"],
            "hours": [9, 18],
            "timezone": "Europe/Moscow",
        },
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SequenceStep(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sequence_steps"
    sequence_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sequences.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(30))
    template_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("templates.id"), nullable=True
    )
    delay_days: Mapped[int] = mapped_column(Integer, default=0)
    send_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
