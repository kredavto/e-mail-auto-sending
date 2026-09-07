from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.warmup.schemas import WarmupAction, WarmupResponse, WarmupStart
from app.modules.warmup.service import WarmupService

router = APIRouter(prefix="/warmup", tags=["warmup"])


@router.post("/start", response_model=WarmupResponse)
async def start(
    data: WarmupStart,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> WarmupResponse:
    return WarmupResponse.model_validate(await WarmupService(db, tenant.workspace_id).start(data))


@router.post("/pause", response_model=WarmupResponse)
async def pause(
    data: WarmupAction,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> WarmupResponse:
    return WarmupResponse.model_validate(
        await WarmupService(db, tenant.workspace_id).pause(data.domain_id)
    )


@router.get("/status/{domain_id}", response_model=WarmupResponse)
async def status(
    domain_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> WarmupResponse:
    service = WarmupService(db, tenant.workspace_id)
    return WarmupResponse.model_validate(await service.advance(await service.get(domain_id)))


@router.get("/schedule/{domain_id}")
async def schedule(
    domain_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    return await WarmupService(db, tenant.workspace_id).schedule(domain_id)


@router.post("/complete", response_model=WarmupResponse)
async def complete(
    data: WarmupAction,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> WarmupResponse:
    return WarmupResponse.model_validate(
        await WarmupService(db, tenant.workspace_id).complete(data.domain_id)
    )
