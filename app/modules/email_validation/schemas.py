from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.shared.dto import ORMModel


class ValidateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    smtp_check: bool = False


class ValidateBatchRequest(BaseModel):
    emails: list[str] = Field(min_length=1, max_length=1000)
    smtp_check: bool = False


class ValidationResponse(ORMModel):
    id: UUID | None = None
    email: str
    status: str
    score: int
    is_disposable: bool
    is_role_based: bool
    has_mx_records: bool
    smtp_check_passed: bool
    is_spam_trap: bool
    provider: str
    details: dict[str, object] = Field(default_factory=dict)


class EmailLookup(BaseModel):
    email: EmailStr
