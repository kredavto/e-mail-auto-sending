from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.campaigns.models import Campaign
from app.modules.contacts.models import Contact
from app.modules.omnichannel.schemas import OrchestrateRequest
from app.modules.omnichannel.service import OmnichannelOrchestrator
from app.modules.omnichannel.tasks import orchestrate_step
from app.modules.sequences.models import SequenceStep

router = APIRouter(prefix="/omnichannel", tags=["omnichannel"])


@router.post("/orchestrate", status_code=202)
async def orchestrate(
    data: OrchestrateRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    campaign = await db.get(Campaign, data.campaign_id)
    contact = await db.get(Contact, data.contact_id)
    step = await db.get(SequenceStep, data.step_id)
    if (
        not campaign
        or not contact
        or not step
        or campaign.workspace_id != tenant.workspace_id
        or contact.workspace_id != tenant.workspace_id
        or step.sequence_id != campaign.sequence_id
    ):
        raise NotFoundError("Шаг омниканальной цепочки не найден")
    task = orchestrate_step.delay(
        str(tenant.workspace_id), str(campaign.id), str(contact.id), str(step.id)
    )
    return {"task_id": str(task.id), "status": "queued"}


@router.get("/channels/{contact_id}")
async def channels(
    contact_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    contact = await db.get(Contact, contact_id)
    if not contact or contact.workspace_id != tenant.workspace_id:
        raise NotFoundError("Контакт не найден")
    return await OmnichannelOrchestrator(db, tenant.workspace_id).channels(contact_id)


@router.get("/stats")
async def stats(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    return await OmnichannelOrchestrator(db, tenant.workspace_id).stats()
