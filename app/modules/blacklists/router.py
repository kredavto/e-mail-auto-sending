from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.blacklists.schemas import BlacklistCheckRequest, SubscribeRequest
from app.modules.blacklists.service import BlacklistService

router = APIRouter(prefix="/blacklists", tags=["blacklists"])


def check_dict(row: object) -> dict[str, object]:
    return {
        name: getattr(row, name)
        for name in (
            "id",
            "domain_id",
            "ip_address",
            "blacklist",
            "listed",
            "return_code",
            "error",
            "created_at",
        )
    }


@router.post("/check")
async def check(
    data: BlacklistCheckRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    return [
        check_dict(row)
        for row in await BlacklistService(db, tenant.workspace_id).check(data.domain_id)
    ]


@router.get("/history/{domain_id}")
async def history(
    domain_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    return [
        check_dict(row)
        for row in await BlacklistService(db, tenant.workspace_id).history(domain_id)
    ]


@router.post("/subscribe", status_code=201)
async def subscribe(
    data: SubscribeRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    row = await BlacklistService(db, tenant.workspace_id).subscribe(
        data.domain_id, str(data.notification_email)
    )
    return {
        "id": row.id,
        "domain_id": row.domain_id,
        "notification_email": row.notification_email,
        "is_active": row.is_active,
    }


@router.get("/alerts")
async def alerts(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, object]]:
    return [
        {
            "id": row.id,
            "domain_id": row.domain_id,
            "blacklist": row.blacklist,
            "ip_address": row.ip_address,
            "message": row.message,
            "acknowledged": row.acknowledged,
            "created_at": row.created_at,
        }
        for row in await BlacklistService(db, tenant.workspace_id).alerts()
    ]
