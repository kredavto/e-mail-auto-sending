from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.database import get_db
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.schemas import AuditLogPage, AuditLogResponse
from app.modules.audit.service import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


def require_auditor(tenant: TenantContext) -> None:
    if tenant.role not in {"owner", "admin"}:
        raise PermissionDeniedError("Журнал аудита доступен владельцу и администраторам")


async def filtered_logs(
    db: AsyncSession,
    tenant: TenantContext,
    *,
    page: int,
    page_size: int,
    user_id: UUID | None,
    action: str | None,
    resource_type: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[list[AuditLog], int]:
    return await AuditLogRepository(db, tenant.workspace_id).list(
        offset=(page - 1) * page_size,
        limit=page_size,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/logs", response_model=AuditLogPage)
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: UUID | None = None,
    action: str | None = Query(default=None, max_length=100),
    resource_type: str | None = Query(default=None, max_length=50),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> AuditLogPage:
    require_auditor(tenant)
    rows, total = await filtered_logs(
        db,
        tenant,
        page=page,
        page_size=page_size,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
    )
    return AuditLogPage(
        items=[AuditLogResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/logs/{log_id}", response_model=AuditLogResponse)
async def get_log(
    log_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> AuditLogResponse:
    require_auditor(tenant)
    row = await AuditLogRepository(db, tenant.workspace_id).get(log_id)
    if not row:
        raise NotFoundError("Запись аудита не найдена")
    return AuditLogResponse.model_validate(row)


@router.get("/export")
async def export_logs(
    format: Literal["csv", "pdf"] = "csv",
    user_id: UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    require_auditor(tenant)
    rows, _ = await AuditLogRepository(db, tenant.workspace_id).list(
        limit=10_000,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
    )
    content, media_type = await AuditService(db, tenant.workspace_id).export(
        rows, format, tenant.user.id
    )
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="audit-log.{format}"'},
    )
