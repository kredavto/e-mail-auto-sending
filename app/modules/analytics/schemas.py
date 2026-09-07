from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class GenerateReportRequest(BaseModel):
    report_type: Literal["dashboard", "products", "campaigns"] = "dashboard"
    format: Literal["csv", "json"] = "csv"
    period: Literal["7d", "30d", "90d", "365d"] = "30d"
    product_id: UUID | None = None
    campaign_id: UUID | None = None


class ReportCreated(BaseModel):
    id: UUID
    status: str
    format: str


class TrendPoint(BaseModel):
    date: str
    sent: int
    delivered: int
    opened: int
    clicked: int
    replied: int
    bounced: int
    meetings: int
