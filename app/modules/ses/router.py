from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.ses.client import SESClient
from app.modules.ses.schemas import DomainVerifyRequest, SESStatisticsResponse, WebhookResponse
from app.modules.ses.service import SESWebhookHandler

router = APIRouter(prefix="/ses", tags=["ses"])


@router.post("/webhook", response_model=WebhookResponse, include_in_schema=True)
async def webhook(request: Request, db: AsyncSession = Depends(get_db)) -> WebhookResponse:
    payload: dict[str, Any] = await request.json()
    event = await SESWebhookHandler(db).handle(payload)
    return WebhookResponse(status="ok", event=event)


@router.get("/quota")
async def quota(_tenant: TenantContext = Depends(get_tenant_context)) -> dict[str, object]:
    return await SESClient().get_send_quota()


@router.get("/statistics", response_model=SESStatisticsResponse)
async def statistics(_tenant: TenantContext = Depends(get_tenant_context)) -> SESStatisticsResponse:
    return SESStatisticsResponse(points=await SESClient().get_send_statistics())


@router.post("/domains/verify")
async def verify_domain(
    data: DomainVerifyRequest, _tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, str]:
    token = await SESClient().verify_domain_identity(data.domain)
    return {"domain": data.domain, "verification_token": token}


@router.get("/domains/{domain}/status")
async def domain_status(
    domain: str, _tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, str]:
    normalized = DomainVerifyRequest(domain=domain).domain
    status = await SESClient().get_domain_verification(normalized)
    return {"domain": normalized, "status": status}
