from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel


class SignatureCreate(BaseModel):
    name: str
    html_template: str
    logo_url: str | None = None
    photo_url: str | None = None
    social_links: dict[str, str] = Field(default_factory=dict)
    disclaimer: str = ""
    is_default: bool = False


class SignatureResponse(SignatureCreate, ORMModel):
    id: UUID


class SignatureUpdate(BaseModel):
    name: str | None = None
    html_template: str | None = None
    logo_url: str | None = None
    photo_url: str | None = None
    social_links: dict[str, str] | None = None
    disclaimer: str | None = None
    is_default: bool | None = None


class SignatureRenderRequest(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict)


class SignatureRenderResponse(BaseModel):
    html: str
