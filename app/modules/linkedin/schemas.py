from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class EnrichRequest(BaseModel):
    profile_ids: list[UUID] = Field(default_factory=list, max_length=5000)


class LeadGenSyncRequest(BaseModel):
    ad_account_id: str = Field(min_length=1, max_length=100)


class MatchedAudienceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    emails: list[EmailStr] = Field(min_length=1, max_length=300000)


class LinkedInProfileResponse(BaseModel):
    id: UUID
    linkedin_id: str
    first_name: str
    last_name: str
    headline: str
    company_name: str
    email: str | None
    email_confidence: int | None
    profile_url: str

    model_config = {"from_attributes": True}
