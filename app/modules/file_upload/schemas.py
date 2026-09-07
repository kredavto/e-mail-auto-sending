from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.dto import ORMModel


class FileResponse(ORMModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: str


class PreviewResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, object]]
    delimiter: str | None = None
    encoding: str | None = None


class ParseRequest(BaseModel):
    mapping: dict[str, str]
    skip_rows: int = Field(default=0, ge=0)
