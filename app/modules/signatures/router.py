from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.signatures.repository import SignatureRepository
from app.modules.signatures.schemas import (
    SignatureCreate,
    SignatureRenderRequest,
    SignatureRenderResponse,
    SignatureResponse,
    SignatureUpdate,
)
from app.modules.signatures.service import SignatureService

router = APIRouter(prefix="/signatures", tags=["signatures"])


@router.get("", response_model=list[SignatureResponse])
async def list_items(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[SignatureResponse]:
    return [
        SignatureResponse.model_validate(i)
        for i in await SignatureRepository(db, tenant.workspace_id).list_all()
    ]


@router.post("", response_model=SignatureResponse, status_code=201)
async def create_item(
    data: SignatureCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SignatureResponse:
    return SignatureResponse.model_validate(
        await SignatureService(db, tenant.workspace_id).create(data)
    )


@router.patch("/{item_id}", response_model=SignatureResponse)
async def update_item(
    item_id: UUID,
    data: SignatureUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SignatureResponse:
    return SignatureResponse.model_validate(
        await SignatureService(db, tenant.workspace_id).update(item_id, data)
    )


@router.delete("/{item_id}", status_code=204)
async def delete_item(
    item_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await SignatureRepository(db, tenant.workspace_id).delete(item_id):
        raise NotFoundError("Подпись не найдена")
    return Response(status_code=204)


@router.post("/{item_id}/render", response_model=SignatureRenderResponse)
async def render(
    item_id: UUID,
    data: SignatureRenderRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SignatureRenderResponse:
    return SignatureRenderResponse(
        html=await SignatureService(db, tenant.workspace_id).render(item_id, data.variables)
    )
