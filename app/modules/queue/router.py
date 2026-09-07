from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.queue.repository import QueueRepository
from app.modules.queue.schemas import FailedTaskResponse, QueueStats
from app.modules.queue.service import QueueService
from app.shared.dto import MessageResponse

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("/stats", response_model=QueueStats)
async def stats(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> QueueStats:
    return QueueStats(queues=await QueueService(db, tenant.workspace_id).stats(), workers=0)


@router.get("/failed", response_model=list[FailedTaskResponse])
async def failed(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[FailedTaskResponse]:
    return [
        FailedTaskResponse.model_validate(i)
        for i in await QueueRepository(db, tenant.workspace_id).list_failed()
    ]


@router.post("/failed/{item_id}/retry", response_model=MessageResponse)
async def retry(
    item_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await QueueService(db, tenant.workspace_id).retry(item_id)
    return MessageResponse(message="Задача поставлена повторно")
