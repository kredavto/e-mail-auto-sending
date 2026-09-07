from pydantic import BaseModel, EmailStr, Field, field_validator


class FindEmailRequest(BaseModel):
    domain: str
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)

    @field_validator("domain")
    @classmethod
    def domain_only(cls, value: str) -> str:
        normalized = value.strip().casefold().rstrip(".")
        if "." not in normalized or "/" in normalized or "@" in normalized:
            raise ValueError("Некорректный домен")
        return normalized


class VerifyEmailRequest(BaseModel):
    email: EmailStr


class DomainSearchRequest(BaseModel):
    domain: str

    @field_validator("domain")
    @classmethod
    def domain_only(cls, value: str) -> str:
        return FindEmailRequest(domain=value, first_name="x", last_name="x").domain
