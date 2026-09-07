from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.templates.repository import TemplateRepository
from app.modules.templates.schemas import (
    RollbackRequest,
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
    TemplateVersionResponse,
)
from app.modules.templates.service import TemplateService

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    product_id: UUID | None = None,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateResponse]:
    return [
        TemplateResponse.model_validate(i)
        for i in await TemplateRepository(db, tenant.workspace_id).list_all(product_id)
    ]


@router.post("", response_model=TemplateResponse, status_code=201)
async def create_template(
    data: TemplateCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    return TemplateResponse.model_validate(
        await TemplateService(db, tenant.workspace_id).create(data)
    )


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    item = await TemplateRepository(db, tenant.workspace_id).get(template_id)
    if not item:
        raise NotFoundError("Шаблон не найден")
    return TemplateResponse.model_validate(item)


@router.patch("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: UUID,
    data: TemplateUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    return TemplateResponse.model_validate(
        await TemplateService(db, tenant.workspace_id).update(template_id, data)
    )


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await TemplateRepository(db, tenant.workspace_id).delete(template_id):
        raise NotFoundError("Шаблон не найден")
    return Response(status_code=204)


@router.get("/{template_id}/versions", response_model=list[TemplateVersionResponse])
async def versions(
    template_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateVersionResponse]:
    return [
        TemplateVersionResponse.model_validate(i)
        for i in await TemplateRepository(db, tenant.workspace_id).versions(template_id)
    ]


@router.post("/{template_id}/rollback", response_model=TemplateResponse)
async def rollback(
    template_id: UUID,
    data: RollbackRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    return TemplateResponse.model_validate(
        await TemplateService(db, tenant.workspace_id).rollback(template_id, data.version)
    )
