from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.scheduler.repository import SchedulerRepository
from app.modules.scheduler.schemas import SchedulerStatus, UpcomingItem

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/status", response_model=SchedulerStatus)
async def status(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> SchedulerStatus:
    now = datetime.now(UTC)
    due = await SchedulerRepository(db, tenant.workspace_id).due(now)
    return SchedulerStatus(enabled=True, due_count=len(due), checked_at=now)


@router.get("/upcoming", response_model=list[UpcomingItem])
async def upcoming(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[UpcomingItem]:
    rows = await SchedulerRepository(db, tenant.workspace_id).upcoming(datetime.now(UTC))
    return [
        UpcomingItem(
            campaign_id=i.campaign_id,
            contact_id=i.contact_id,
            step_index=i.current_step_index,
            send_at=i.next_send_at,
        )
        for i in rows
        if i.next_send_at
    ]
