from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.shared.dto import ORMModel


class CampaignCreate(BaseModel):
    product_id: UUID
    name: str
    sequence_id: UUID | None = None
    sender_email: EmailStr
    sender_name: str
    schedule_start: datetime
    contact_ids: list[UUID] = Field(default_factory=list, max_length=100000)


class CampaignResponse(ORMModel):
    id: UUID
    product_id: UUID
    name: str
    sequence_id: UUID
    sender_email: EmailStr
    sender_name: str
    schedule_start: datetime
    status: str


class CampaignUpdate(BaseModel):
    name: str | None = None
    sequence_id: UUID | None = None
    sender_email: EmailStr | None = None
    sender_name: str | None = None
    schedule_start: datetime | None = None


class CampaignStats(BaseModel):
    sent: int
    opened: int
    clicked: int
    replied: int
    bounced: int
    open_rate: float
    reply_rate: float
