from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.shared.validators import StrongPasswordModel


class RegisterRequest(StrongPasswordModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MFALoginRequest(LoginRequest):
    code: str = Field(pattern=r"^\d{6}$")


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    mfa_required: bool = False


class MFASetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MFAVerifyRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class SessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None


class ResetRequest(BaseModel):
    email: EmailStr
