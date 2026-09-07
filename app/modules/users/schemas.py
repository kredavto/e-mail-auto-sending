from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.shared.dto import ORMModel
from app.shared.types import WorkspaceRole


class UserResponse(ORMModel):
    id: UUID
    email: EmailStr
    full_name: str
    mfa_enabled: bool


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")


class WorkspaceResponse(ORMModel):
    id: UUID
    name: str
    slug: str
    owner_id: UUID


class InvitationCreate(BaseModel):
    email: EmailStr
    role: WorkspaceRole


class InvitationResponse(ORMModel):
    id: UUID
    workspace_id: UUID
    email: EmailStr
    role: str
    expires_at: datetime
    invite_token: str | None = None


class InvitationAccept(BaseModel):
    token: str


class MemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: EmailStr
    full_name: str
    role: str
