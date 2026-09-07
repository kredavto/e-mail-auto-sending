from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel


class WarmupAction(BaseModel):
    domain_id: UUID


class WarmupStart(WarmupAction):
    target_daily_limit: int | None = Field(default=None, ge=20, le=100_000)
    increment_percent: float = Field(default=0.2, gt=0, le=1)
    provider: Literal["internal", "mailwarm", "lemwarm", "warmup_inbox"] = "internal"


class WarmupResponse(ORMModel):
    id: UUID
    domain_id: UUID
    start_date: date
    current_daily_limit: int
    target_daily_limit: int
    increment_percent: float
    status: str
    provider: str
