from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.events import IntegrationEvent, publish_enterprise_event
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.audit.service import AuditService
from app.modules.campaigns.repository import CampaignRepository
from app.modules.campaigns.schemas import (
    CampaignCreate,
    CampaignResponse,
    CampaignStats,
    CampaignUpdate,
)
from app.modules.campaigns.service import CampaignService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[CampaignResponse]:
    return [
        CampaignResponse.model_validate(i)
        for i in await CampaignRepository(db, tenant.workspace_id).list_all()
    ]


@router.post("", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    data: CampaignCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    return CampaignResponse.model_validate(
        await CampaignService(db, tenant.workspace_id).create(data)
    )


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: UUID,
    data: CampaignUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    return CampaignResponse.model_validate(
        await CampaignService(db, tenant.workspace_id).update(campaign_id, data)
    )


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await CampaignRepository(db, tenant.workspace_id).delete(campaign_id):
        raise NotFoundError("Удалить можно только существующую draft-кампанию")
    await AuditService(db, tenant.workspace_id).log(
        "campaign.deleted",
        "campaign",
        user_id=tenant.user.id,
        resource_id=campaign_id,
    )
    return Response(status_code=204)


@router.post("/{campaign_id}/start", response_model=CampaignResponse)
async def start(
    campaign_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    row = await CampaignService(db, tenant.workspace_id).transition(campaign_id, "running")
    await publish_enterprise_event(
        db,
        IntegrationEvent(
            workspace_id=tenant.workspace_id,
            actor_id=tenant.user.id,
            resource_type="campaign",
            resource_id=row.id,
            data={"name": row.name},
            kind="campaign.started",
        ),
    )
    return CampaignResponse.model_validate(row)


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
async def pause(
    campaign_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    row = await CampaignService(db, tenant.workspace_id).transition(campaign_id, "paused")
    await publish_enterprise_event(
        db,
        IntegrationEvent(
            workspace_id=tenant.workspace_id,
            actor_id=tenant.user.id,
            resource_type="campaign",
            resource_id=row.id,
            data={"name": row.name},
            kind="campaign.paused",
        ),
    )
    return CampaignResponse.model_validate(row)


@router.get("/{campaign_id}/stats", response_model=CampaignStats)
async def stats(
    campaign_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> CampaignStats:
    item = await CampaignRepository(db, tenant.workspace_id).get(campaign_id)
    if not item:
        raise NotFoundError("Кампания не найдена")
    return CampaignService.stats(item)
