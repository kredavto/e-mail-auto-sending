from uuid import UUID

from pydantic import BaseModel, EmailStr


class SendEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    html: str
    text: str
    sender_email: EmailStr
    sender_name: str
    campaign_id: UUID | None = None
    contact_id: UUID | None = None


class SendEmailResponse(BaseModel):
    message_id: UUID
    status: str


class SMTPTestRequest(BaseModel):
    recipient: EmailStr
