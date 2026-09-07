from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel


class AuditLogResponse(ORMModel):
    id: UUID
    workspace_id: UUID
    user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    old_values: dict[str, object] | None
    new_values: dict[str, object] | None
    ip_address: str | None
    user_agent: str | None
    request_id: str | None
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
