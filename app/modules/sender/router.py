from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.sender.schemas import SendEmailRequest, SendEmailResponse, SMTPTestRequest
from app.modules.sender.service import SenderService

router = APIRouter(prefix="/sender", tags=["sender"])


@router.post("/send", response_model=SendEmailResponse)
async def send(
    data: SendEmailRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SendEmailResponse:
    row = await SenderService(db, tenant.workspace_id).send(data)
    return SendEmailResponse(message_id=row.id, status=row.status)


@router.post("/test-smtp", response_model=SendEmailResponse)
async def test_smtp(
    data: SMTPTestRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SendEmailResponse:
    request = SendEmailRequest(
        to=data.recipient,
        subject="SMTP test",
        html="<p>SMTP работает</p>",
        text="SMTP работает",
        sender_email="test@localhost",
        sender_name="Premium Mailer",
    )
    return await send(request, tenant, db)
