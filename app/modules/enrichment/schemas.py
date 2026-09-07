from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel


class EnrichBatchRequest(BaseModel):
    contact_ids: list[UUID] = Field(min_length=1, max_length=1000)


class EnrichmentResponse(ORMModel):
    id: UUID
    contact_id: UUID
    email: str | None
    source: str | None
    confidence: int
    enriched_data: dict[str, object]
