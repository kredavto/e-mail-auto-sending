from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.quality.schemas import QualityCheckRequest, QualityReport
from app.modules.quality.service import QualityChecker
from app.modules.templates.repository import TemplateRepository

router = APIRouter(prefix="/quality", tags=["quality"])


@router.post("/check", response_model=QualityReport)
async def check(data: QualityCheckRequest) -> QualityReport:
    return QualityChecker().check(data.html, data.text, data.subject)


@router.get("/suggestions/{template_id}", response_model=QualityReport)
async def suggestions(
    template_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> QualityReport:
    template = await TemplateRepository(db, tenant.workspace_id).get(template_id)
    if not template:
        raise NotFoundError("Шаблон не найден")
    return QualityChecker().check(template.html_body, template.text_body, template.subject_template)
