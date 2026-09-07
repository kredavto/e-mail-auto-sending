from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel

TemplateCategory = Literal["first_contact", "second", "warmup", "cta", "reminder"]


class TemplateCreate(BaseModel):
    product_id: UUID | None = None
    name: str
    category: TemplateCategory
    subject_template: str = Field(max_length=255)
    editor_state: dict[str, object]
    signature_id: UUID | None = None


class TemplateUpdate(BaseModel):
    name: str | None = None
    category: TemplateCategory | None = None
    subject_template: str | None = None
    editor_state: dict[str, object] | None = None
    signature_id: UUID | None = None


class TemplateResponse(ORMModel):
    id: UUID
    product_id: UUID | None
    name: str
    category: str
    subject_template: str
    editor_state: dict[str, object]
    html_body: str
    text_body: str
    variables: list[str]
    quality_score: int
    version: int


class TemplateVersionResponse(ORMModel):
    id: UUID
    version: int
    subject_template: str
    quality_score: int


class RollbackRequest(BaseModel):
    version: int = Field(ge=1)
