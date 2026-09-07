from uuid import UUID

from pydantic import BaseModel


class OrchestrateRequest(BaseModel):
    campaign_id: UUID
    contact_id: UUID
    step_id: UUID


class StepResultResponse(BaseModel):
    status: str
    channel: str
    reason: str | None = None
    message_id: str | None = None
