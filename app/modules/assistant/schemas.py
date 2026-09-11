from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, EmailStr, Field

from app.modules.templates.schemas import TemplateCategory
from app.shared.dto import ORMModel


class AskRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=6000)
    mode: Literal["draft", "advice", "schedule"] = "advice"
    stage: TemplateCategory = "first_contact"
    template_id: UUID | None = None
    campaign_id: UUID | None = None


class Draft(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=255)
    paragraphs: list[str] = Field(min_length=1, max_length=12)
    cta_label: str | None
    cta_url: str | None


class AgentAnswer(BaseModel):
    message: str = Field(max_length=8000)
    next_steps: list[str] = Field(max_length=6)
    draft: Draft | None
    action: Literal["none", "start", "pause", "reschedule"]
    send_at: str | None


class RunResponse(ORMModel):
    id: UUID
    prompt: str
    model: str
    status: str
    result: dict
    input_tokens: int
    output_tokens: int
    created_at: datetime
    applied_at: datetime | None


class ConfirmRequest(BaseModel):
    confirmed: Literal[True]


class ActionRequest(BaseModel):
    action: Literal["start", "pause", "reschedule"]
    send_at: AwareDatetime | None = None


class CampaignDraftRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    product_name: str = Field(min_length=2, max_length=200)
    template_ids: list[UUID] = Field(min_length=1, max_length=5)
    contact_ids: list[UUID] = Field(min_length=1, max_length=1000)
    sender_email: EmailStr
    sender_name: str = Field(min_length=1, max_length=100)
    schedule_start: AwareDatetime
    delay_days: int = Field(default=3, ge=1, le=30)
    consent_confirmed: Literal[True]
