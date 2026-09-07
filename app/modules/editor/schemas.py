from pydantic import BaseModel, Field


class CompileRequest(BaseModel):
    editor_state: dict[str, object]


class CompileResponse(BaseModel):
    html: str
    text: str
    variables: list[str]
    quality_score: int
    warnings: list[str]


class PreviewRequest(CompileRequest):
    variables: dict[str, str] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    html: str
