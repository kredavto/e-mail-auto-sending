from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.shared.dto import ORMModel

MAX_IMPORT_CONTACTS = 70000


class ContactBase(BaseModel):
    email: EmailStr
    full_name: str = ""
    company: str = ""
    position: str = "Директор"
    industry: str | None = None
    current_site_url: str | None = None
    company_size: str | None = None
    annual_revenue_tier: str | None = None
    phone: str | None = None
    source: str = "manual"
    tags: list[str] = Field(default_factory=list)
    custom_fields: dict[str, object] = Field(default_factory=dict)
    linkedin_url: str | None = None
    tenchat_user_id: str | None = None


class ContactCreate(ContactBase):
    # Preserve explicit spreadsheet name parts instead of guessing their order.
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    patronymic: str | None = Field(default=None, max_length=100)


class ContactUpdate(BaseModel):
    full_name: str | None = None
    company: str | None = None
    position: str | None = None
    industry: str | None = None
    company_size: str | None = None
    annual_revenue_tier: str | None = None
    phone: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, object] | None = None
    linkedin_url: str | None = None
    tenchat_user_id: str | None = None


class ContactResponse(ContactBase, ORMModel):
    id: UUID
    last_name: str
    first_name: str
    patronymic: str | None
    status: str
    has_replied: bool
    bitrix_lead_id: int | None
    bitrix_contact_id: int | None
    bitrix_company_id: int | None


class BulkContactsCreate(BaseModel):
    contacts: list[ContactCreate] = Field(max_length=MAX_IMPORT_CONTACTS)


class BulkResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]


class SegmentCreate(BaseModel):
    name: str
    description: str = ""
    filters: dict[str, object] = Field(default_factory=dict)


class SegmentResponse(SegmentCreate, ORMModel):
    id: UUID
