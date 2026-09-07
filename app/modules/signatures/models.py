from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class Signature(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "signatures"
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    html_template: Mapped[str] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    social_links: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    disclaimer: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
