from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.analytics.schemas import GenerateReportRequest, ReportCreated
from app.modules.analytics.service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])
Period = Literal["7d", "30d", "90d", "365d"]


@router.get("/dashboard")
async def dashboard(
    period: Period = "30d",
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await AnalyticsService(db, tenant.workspace_id).dashboard(period)


@router.get("/products/{product_id}")
async def product(
    product_id: UUID,
    period: Period = "30d",
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await AnalyticsService(db, tenant.workspace_id).get_product_stats(product_id, period)


@router.get("/campaigns/{campaign_id}")
async def campaign(
    campaign_id: UUID,
    period: Period = "30d",
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await AnalyticsService(db, tenant.workspace_id).get_campaign_stats(campaign_id, period)


@router.get("/contacts/{contact_id}")
async def contact(
    contact_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await AnalyticsService(db, tenant.workspace_id).contact_stats(contact_id)


@router.get("/trends")
async def trends(
    period: Period = "30d",
    product_id: UUID | None = None,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    return await AnalyticsService(db, tenant.workspace_id).trends(period, product_id)


@router.post("/reports/generate", response_model=ReportCreated, status_code=201)
async def generate(
    data: GenerateReportRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ReportCreated:
    row = await AnalyticsService(db, tenant.workspace_id).generate_report(data)
    return ReportCreated(id=row.id, status=row.status, format=row.format)


@router.get("/reports/{report_id}/download")
async def download(
    report_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await AnalyticsService(db, tenant.workspace_id).get_report(report_id)
    media = "application/json" if row.format == "json" else "text/csv; charset=utf-8"
    return Response(
        row.content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="analytics-{row.id}.{row.format}"'},
    )
