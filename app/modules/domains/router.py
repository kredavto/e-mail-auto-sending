from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.events import IntegrationEvent, publish_enterprise_event
from app.database import get_db
from app.modules.billing.service import BillingService
from app.modules.domains.schemas import DomainCreate, DomainResponse, VerificationResponse
from app.modules.domains.service import DomainService

router = APIRouter(prefix="/domains", tags=["domains"])


@router.get("", response_model=list[DomainResponse])
async def list_domains(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[DomainResponse]:
    return [
        DomainResponse.model_validate(row)
        for row in await DomainService(db, tenant.workspace_id).list_all()
    ]


@router.post("", response_model=DomainResponse, status_code=201)
async def create(
    data: DomainCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DomainResponse:
    await BillingService(db, tenant.workspace_id).check_limits("add_domain")
    row = await DomainService(db, tenant.workspace_id).create(data)
    await publish_enterprise_event(
        db,
        IntegrationEvent(
            workspace_id=tenant.workspace_id,
            actor_id=tenant.user.id,
            resource_type="domain",
            resource_id=row.id,
            data={"domain": row.domain},
            kind="domain.created",
        ),
    )
    return DomainResponse.model_validate(row)


@router.post("/{domain_id}/verify", response_model=VerificationResponse)
async def verify(
    domain_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> VerificationResponse:
    service = DomainService(db, tenant.workspace_id)
    verification = await service.verify(domain_id)
    domain = await service.get(domain_id)
    return VerificationResponse(
        spf_present=verification.spf_present,
        dkim_valid=verification.dkim_valid,
        dmarc_present=verification.dmarc_present,
        status=domain.status,
        reputation_score=domain.reputation_score,
        details=verification.details,
    )


@router.get("/{domain_id}/dns-records")
async def dns_records(
    domain_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await DomainService(db, tenant.workspace_id).dns_records(domain_id)


@router.get("/{domain_id}/reputation")
async def reputation(
    domain_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await DomainService(db, tenant.workspace_id).reputation(domain_id)


@router.delete("/{domain_id}", status_code=204)
async def delete(
    domain_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await DomainService(db, tenant.workspace_id).delete(domain_id)
    return Response(status_code=204)
