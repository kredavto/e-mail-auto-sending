from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel


class ProductBase(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    description: str = ""
    category: str
    average_check: float = Field(default=0, ge=0)
    monthly_fee: float = Field(default=0, ge=0)
    setup_fee: float = Field(default=0, ge=0)
    target_audience: dict[str, list[str]] = Field(default_factory=dict)
    buyer_personas: list[dict[str, object]] = Field(default_factory=list)
    default_sequence_id: UUID | None = None
    default_template_id: UUID | None = None
    is_active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    average_check: float | None = Field(default=None, ge=0)
    monthly_fee: float | None = Field(default=None, ge=0)
    setup_fee: float | None = Field(default=None, ge=0)
    target_audience: dict[str, list[str]] | None = None
    buyer_personas: list[dict[str, object]] | None = None
    default_sequence_id: UUID | None = None
    default_template_id: UUID | None = None
    is_active: bool | None = None


class ProductResponse(ProductBase, ORMModel):
    id: UUID
    workspace_id: UUID


class ProductMatch(BaseModel):
    product: ProductResponse
    score: float
    reasons: list[str]
