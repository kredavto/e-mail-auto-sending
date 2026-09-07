from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.enrichment.schemas import EnrichBatchRequest, EnrichmentResponse
from app.modules.enrichment.service import EnrichmentOrchestrator

router = APIRouter(prefix="/enrichment", tags=["enrichment"])


@router.post("/enrich/{contact_id}", response_model=EnrichmentResponse)
async def enrich(
    contact_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> EnrichmentResponse:
    return EnrichmentResponse.model_validate(
        await EnrichmentOrchestrator(db, tenant.workspace_id).enrich(contact_id)
    )


@router.post("/enrich-batch", response_model=list[EnrichmentResponse])
async def enrich_batch(
    data: EnrichBatchRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[EnrichmentResponse]:
    service = EnrichmentOrchestrator(db, tenant.workspace_id)
    return [
        EnrichmentResponse.model_validate(await service.enrich(contact_id))
        for contact_id in dict.fromkeys(data.contact_ids)
    ]


@router.get("/stats")
async def stats(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    return await EnrichmentOrchestrator(db, tenant.workspace_id).stats()


@router.get("/sources")
async def sources(_tenant: TenantContext = Depends(get_tenant_context)) -> list[dict[str, object]]:
    return EnrichmentOrchestrator.sources()
