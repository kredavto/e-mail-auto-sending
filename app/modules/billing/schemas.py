from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel

PlanName = Literal["free", "pro", "business", "enterprise"]
PaymentProviderName = Literal["yookassa", "stripe", "tinkoff"]


class SubscribeRequest(BaseModel):
    plan: PlanName
    provider: PaymentProviderName = "yookassa"
    return_url: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


class CheckoutResponse(BaseModel):
    invoice_id: UUID
    status: str
    checkout_url: str | None


class SubscriptionResponse(ORMModel):
    id: UUID
    workspace_id: UUID
    plan: str
    status: str
    provider: str | None
    current_period_start: datetime
    current_period_end: datetime
    cancel_at: datetime | None


class UsageItem(BaseModel):
    metric: str
    count: int
    limit: int | None
    percent: float | None


class UsageResponse(BaseModel):
    plan: str
    free_plan_test_mode: bool = False
    period_start: datetime
    period_end: datetime
    items: list[UsageItem]


class InvoiceResponse(ORMModel):
    id: UUID
    amount: Decimal
    currency: str
    status: str
    paid_at: datetime | None
    pdf_url: str | None
    checkout_url: str | None
    created_at: datetime
