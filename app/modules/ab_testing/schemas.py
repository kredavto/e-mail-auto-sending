from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.shared.dto import ORMModel

TestType = Literal["subject", "body", "cta", "sender_name", "send_time"]
Metric = Literal["open_rate", "reply_rate", "click_rate", "meeting_rate"]


class VariantCreate(BaseModel):
    variant_key: Literal["A", "B"]
    template_id: UUID | None = None
    subject: str | None = Field(default=None, max_length=255)
    sender_name: str | None = Field(default=None, max_length=100)


class ABTestCreate(BaseModel):
    campaign_id: UUID
    name: str = Field(min_length=1, max_length=200)
    test_type: TestType
    split_ratio: float = Field(default=0.5, gt=0, lt=1)
    sample_size: int = Field(default=0, ge=0)
    confidence_level: float = Field(default=0.95, ge=0.8, lt=1)
    primary_metric: Metric = "reply_rate"
    min_detectable_effect: float = Field(default=0.1, gt=0, le=2)
    variants: list[VariantCreate] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def exactly_a_and_b(self) -> "ABTestCreate":
        if {item.variant_key for item in self.variants} != {"A", "B"}:
            raise ValueError("Тест должен содержать варианты A и B")
        return self


class VariantResponse(ORMModel):
    id: UUID
    variant_key: str
    template_id: UUID | None
    subject: str | None
    sender_name: str | None
    sent_count: int
    opened_count: int
    replied_count: int
    clicked_count: int
    meeting_count: int
    open_rate: float
    reply_rate: float
    click_rate: float
    meeting_rate: float
    p_value: float


class ABTestResponse(ORMModel):
    id: UUID
    campaign_id: UUID
    name: str
    test_type: str
    status: str
    split_ratio: float
    sample_size: int
    confidence_level: float
    primary_metric: str
    min_detectable_effect: float
    winner_variant: str | None


class SelectWinnerRequest(BaseModel):
    variant_key: Literal["A", "B"] | None = None


class AssignmentRequest(BaseModel):
    contact_id: UUID


class SampleSizeRequest(BaseModel):
    baseline: float = Field(gt=0, lt=1)
    mde: float = Field(gt=0, le=2)
    confidence: float = Field(default=0.95, ge=0.8, lt=1)
    power: float = Field(default=0.8, ge=0.5, lt=1)
