from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel


class CaseCreate(BaseModel):
    product_id: UUID
    title: str
    summary: str
    industry: str | None = None
    company_size: str | None = None
    metrics: dict[str, object] = Field(default_factory=dict)
    is_published: bool = False


class CaseResponse(CaseCreate, ORMModel):
    id: UUID


class CaseUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    industry: str | None = None
    company_size: str | None = None
    metrics: dict[str, object] | None = None
    is_published: bool | None = None


class CaseMatch(BaseModel):
    case: CaseResponse
    score: float
