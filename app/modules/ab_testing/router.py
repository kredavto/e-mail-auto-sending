from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.ab_testing.schemas import (
    ABTestCreate,
    ABTestResponse,
    AssignmentRequest,
    SampleSizeRequest,
    SelectWinnerRequest,
)
from app.modules.ab_testing.service import ABTestingService

router = APIRouter(prefix="/ab-tests", tags=["ab-tests"])


def service(db: AsyncSession, tenant: TenantContext) -> ABTestingService:
    return ABTestingService(db, tenant.workspace_id)


@router.post("", response_model=ABTestResponse, status_code=201)
async def create(
    data: ABTestCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ABTestResponse:
    return ABTestResponse.model_validate(await service(db, tenant).create(data))


@router.post("/sample-size")
async def sample_size(
    data: SampleSizeRequest, _tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, int]:
    return {"per_variant": ABTestingService.calculate_required_sample_size(**data.model_dump())}


@router.post("/{test_id}/start", response_model=ABTestResponse)
async def start(
    test_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ABTestResponse:
    return ABTestResponse.model_validate(await service(db, tenant).start(test_id))


@router.post("/{test_id}/stop", response_model=ABTestResponse)
async def stop(
    test_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ABTestResponse:
    return ABTestResponse.model_validate(await service(db, tenant).stop(test_id))


@router.post("/{test_id}/assign")
async def assign(
    test_id: UUID,
    data: AssignmentRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    row = await service(db, tenant).assignment(test_id, data.contact_id)
    return {"variant_key": row.variant_key}


@router.get("/{test_id}/results")
async def results(
    test_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await service(db, tenant).results(test_id)


@router.post("/{test_id}/select-winner", response_model=ABTestResponse)
async def select_winner(
    test_id: UUID,
    data: SelectWinnerRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ABTestResponse:
    return ABTestResponse.model_validate(
        await service(db, tenant).select_winner(test_id, data.variant_key)
    )


@router.post("/{test_id}/apply-winner", response_model=ABTestResponse)
async def apply_winner(
    test_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ABTestResponse:
    return ABTestResponse.model_validate(await service(db, tenant).apply_winner(test_id))
