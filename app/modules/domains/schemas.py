from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.shared.dto import ORMModel


class DomainCreate(BaseModel):
    domain: str
    dkim_records: list[dict[str, str]] = Field(default_factory=list)
    daily_limit: int = Field(default=200, ge=1, le=100_000)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        domain = value.strip().casefold().rstrip(".")
        if "." not in domain or "/" in domain or "@" in domain:
            raise ValueError("Некорректный домен")
        return domain


class DomainResponse(ORMModel):
    id: UUID
    domain: str
    status: str
    dkim_enabled: bool
    dkim_records: list[dict[str, str]]
    spf_record: str | None
    dmarc_record: str | None
    daily_limit: int
    current_daily_count: int
    reputation_score: int


class VerificationResponse(BaseModel):
    spf_present: bool
    dkim_valid: bool
    dmarc_present: bool
    status: str
    reputation_score: int
    details: dict[str, object]
