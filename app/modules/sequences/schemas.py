from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel


class SequenceCreate(BaseModel):
    product_id: UUID
    name: str
    stop_conditions: dict[str, bool] = Field(
        default_factory=lambda: {
            "replied": True,
            "unsubscribed": True,
            "bounced": True,
            "meeting_booked": True,
        }
    )
    send_window: dict[str, object] = Field(
        default_factory=lambda: {
            "days": ["mon", "tue", "wed", "thu", "fri"],
            "hours": [9, 18],
            "timezone": "Europe/Moscow",
        }
    )


class SequenceResponse(SequenceCreate, ORMModel):
    id: UUID
    is_active: bool


class SequenceUpdate(BaseModel):
    name: str | None = None
    stop_conditions: dict[str, bool] | None = None
    send_window: dict[str, object] | None = None
    is_active: bool | None = None


class StepCreate(BaseModel):
    position: int = Field(ge=0)
    step_type: Literal["email", "tenchat_message", "delay", "condition", "ab_test"]
    template_id: UUID | None = None
    delay_days: int = Field(default=0, ge=0)
    send_hour: int | None = Field(default=None, ge=0, le=23)
    config: dict[str, object] = Field(default_factory=dict)


class StepResponse(StepCreate, ORMModel):
    id: UUID
    sequence_id: UUID


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[str]
