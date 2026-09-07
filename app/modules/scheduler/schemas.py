from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SchedulerStatus(BaseModel):
    enabled: bool
    due_count: int
    checked_at: datetime


class UpcomingItem(BaseModel):
    campaign_id: UUID
    contact_id: UUID
    step_index: int
    send_at: datetime
