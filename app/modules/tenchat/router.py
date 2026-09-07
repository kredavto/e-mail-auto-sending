from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.tenchat.client import TenchatClient
from app.modules.tenchat.models import TenchatProfile
from app.modules.tenchat.schemas import (
    OutreachRequest,
    SearchRequest,
    SyncRequest,
    TenchatProfileResponse,
)
from app.modules.tenchat.tasks import (
    check_incoming_replies,
    send_tenchat_outreach,
    sync_tenchat_profiles,
)

router = APIRouter(prefix="/tenchat", tags=["tenchat"])


@router.post("/search")
async def search(
    data: SearchRequest, _tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, object]:
    return await TenchatClient().search_users(
        data.industry, data.city, data.position, data.per_page
    )


@router.post("/sync", status_code=202)
async def sync(
    data: SyncRequest, tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, str]:
    task = sync_tenchat_profiles.delay(str(tenant.workspace_id), data.user_ids)
    return {"task_id": str(task.id), "status": "queued"}


@router.get("/profiles", response_model=list[TenchatProfileResponse])
async def profiles(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[TenchatProfile]:
    return list(
        (
            await db.scalars(
                select(TenchatProfile)
                .where(TenchatProfile.workspace_id == tenant.workspace_id)
                .order_by(TenchatProfile.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )


@router.post("/outreach", status_code=202)
async def outreach(
    data: OutreachRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    profile = await db.get(TenchatProfile, data.profile_id)
    if not profile or profile.workspace_id != tenant.workspace_id:
        raise NotFoundError("Профиль Tenchat не найден")
    task = send_tenchat_outreach.delay(str(tenant.workspace_id), str(profile.id), data.text)
    return {"task_id": str(task.id), "status": "queued"}


@router.post("/check-replies", status_code=202)
async def check_replies(tenant: TenantContext = Depends(get_tenant_context)) -> dict[str, str]:
    task = check_incoming_replies.delay(str(tenant.workspace_id))
    return {"task_id": str(task.id), "status": "queued"}
