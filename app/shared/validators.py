import re

from pydantic import BaseModel, field_validator

PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{10,}$")


class StrongPasswordModel(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        if not PASSWORD_RE.match(value):
            raise ValueError("Пароль: минимум 10 символов, верхний/нижний регистр и цифра")
        return value
