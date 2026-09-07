from pydantic import BaseModel, Field


class QualityCheckRequest(BaseModel):
    html: str = Field(max_length=1_000_000)
    text: str = Field(max_length=200_000)
    subject: str = Field(default="", max_length=255)


class QualityReport(BaseModel):
    score: int
    issues: list[str]
    warnings: list[str]
    suggestions: list[str]
    words_count: int
    caps_ratio: float
    image_count: int
