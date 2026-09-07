from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class BlacklistCheck(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "blacklist_checks"

    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sending_domains.id", ondelete="CASCADE"), index=True
    )
    ip_address: Mapped[str] = mapped_column(String(45), index=True)
    blacklist: Mapped[str] = mapped_column(String(50), index=True)
    listed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    return_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class BlacklistSubscription(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "blacklist_subscriptions"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sending_domains.id", ondelete="CASCADE"), index=True
    )
    notification_email: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("domain_id", "notification_email"),)


class BlacklistAlert(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "blacklist_alerts"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sending_domains.id", ondelete="CASCADE"), index=True
    )
    blacklist: Mapped[str] = mapped_column(String(50))
    ip_address: Mapped[str] = mapped_column(String(45))
    message: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
