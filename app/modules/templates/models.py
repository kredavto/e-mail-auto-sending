from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin, UUIDMixin


class Template(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "templates"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id"), index=True
    )
    product_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30))
    subject_template: Mapped[str] = mapped_column(String(255))
    editor_state: Mapped[dict[str, object]] = mapped_column(JSONB)
    html_body: Mapped[str] = mapped_column(Text)
    text_body: Mapped[str] = mapped_column(Text)
    signature_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("signatures.id"), nullable=True
    )
    variables: Mapped[list[str]] = mapped_column(JSONB, default=list)
    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class TemplateVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "template_versions"

    template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("templates.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    subject_template: Mapped[str] = mapped_column(String(255))
    editor_state: Mapped[dict[str, object]] = mapped_column(JSONB)
    html_body: Mapped[str] = mapped_column(Text)
    text_body: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(JSONB, default=list)
    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("template_id", "version"),)
