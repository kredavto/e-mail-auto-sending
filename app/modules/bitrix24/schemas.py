from uuid import UUID

from pydantic import BaseModel, Field


class SyncContactsRequest(BaseModel):
    product_id: UUID
    contact_ids: list[UUID] = Field(default_factory=list, max_length=5000)
    campaign_id: UUID | None = None


class SyncContactsResponse(BaseModel):
    task_id: str
    queued: int


class ActivityResponse(BaseModel):
    activities: list[dict[str, object]]
