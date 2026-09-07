from typing import Any

from pydantic import BaseModel, Field, field_validator


class DomainVerifyRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        domain = value.strip().casefold().rstrip(".")
        if "." not in domain or "/" in domain or "@" in domain:
            raise ValueError("Некорректный домен")
        return domain


class WebhookResponse(BaseModel):
    status: str
    event: str


class SESStatisticsResponse(BaseModel):
    points: list[dict[str, Any]]
