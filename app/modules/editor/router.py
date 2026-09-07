from fastapi import APIRouter

from app.modules.editor.schemas import (
    CompileRequest,
    CompileResponse,
    PreviewRequest,
    PreviewResponse,
)
from app.modules.editor.service import EditorService

router = APIRouter(prefix="/editor", tags=["editor"])


@router.post("/compile", response_model=CompileResponse)
async def compile_document(data: CompileRequest) -> CompileResponse:
    html, text, variables, score, warnings = EditorService().compile(data.editor_state)
    return CompileResponse(
        html=html, text=text, variables=variables, quality_score=score, warnings=warnings
    )


@router.post("/preview", response_model=PreviewResponse)
async def preview_document(data: PreviewRequest) -> PreviewResponse:
    return PreviewResponse(html=EditorService().preview(data.editor_state, data.variables))


@router.post("/check-quality", response_model=CompileResponse)
async def check_quality(data: CompileRequest) -> CompileResponse:
    return await compile_document(data)
