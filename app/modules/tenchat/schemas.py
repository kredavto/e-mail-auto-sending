from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    industry: str | None = None
    city: str | None = None
    position: str | None = None
    per_page: int = Field(50, ge=1, le=50)


class SyncRequest(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=1000)


class OutreachRequest(BaseModel):
    profile_id: UUID
    text: str = Field(min_length=1, max_length=5000)


class TenchatProfileResponse(BaseModel):
    id: UUID
    tenchat_user_id: str
    username: str
    display_name: str
    company_name: str
    position: str
    email: str | None

    model_config = {"from_attributes": True}
