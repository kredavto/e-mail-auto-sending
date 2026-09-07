from uuid import UUID

from pydantic import BaseModel, EmailStr


class BlacklistCheckRequest(BaseModel):
    domain_id: UUID


class SubscribeRequest(BaseModel):
    domain_id: UUID
    notification_email: EmailStr
