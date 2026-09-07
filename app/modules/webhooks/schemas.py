from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.core.events import ENTERPRISE_EVENT_TYPES
from app.shared.dto import ORMModel

WEBHOOK_EVENTS = ENTERPRISE_EVENT_TYPES


class WebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    events: list[str] = Field(min_length=1, max_length=50)

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value))
        unknown = set(normalized) - WEBHOOK_EVENTS
        if unknown:
            raise ValueError(f"Неизвестные webhook events: {', '.join(sorted(unknown))}")
        return normalized


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: HttpUrl | None = None
    events: list[str] | None = Field(default=None, min_length=1, max_length=50)
    is_active: bool | None = None

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        normalized = list(dict.fromkeys(value))
        unknown = set(normalized) - WEBHOOK_EVENTS
        if unknown:
            raise ValueError(f"Неизвестные webhook events: {', '.join(sorted(unknown))}")
        return normalized


class WebhookResponse(ORMModel):
    id: UUID
    name: str
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WebhookCreated(WebhookResponse):
    secret: str


class WebhookDeliveryResponse(ORMModel):
    id: UUID
    event_id: UUID
    event_type: str
    response_status: int | None
    response_body: str | None
    delivered_at: datetime | None
    success: bool
    attempts: int
    last_error: str | None
    created_at: datetime
