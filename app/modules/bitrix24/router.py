from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.bitrix24.client import Bitrix24Client
from app.modules.bitrix24.schemas import ActivityResponse, SyncContactsRequest, SyncContactsResponse
from app.modules.bitrix24.service import Bitrix24SyncService
from app.modules.bitrix24.tasks import sync_contacts_batch
from app.modules.contacts.models import Contact

router = APIRouter(prefix="/bitrix", tags=["bitrix24"])


@router.post("/test-connection")
async def test_connection(
    _tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, object]:
    return await Bitrix24Client().test_connection()


@router.post("/sync-contacts", response_model=SyncContactsResponse)
async def sync_contacts(
    data: SyncContactsRequest, tenant: TenantContext = Depends(get_tenant_context)
) -> SyncContactsResponse:
    task = sync_contacts_batch.delay(
        str(tenant.workspace_id),
        str(data.product_id),
        [str(value) for value in data.contact_ids],
        str(data.campaign_id) if data.campaign_id else None,
    )
    return SyncContactsResponse(task_id=str(task.id), queued=len(data.contact_ids))


@router.get("/activities/{contact_id}", response_model=ActivityResponse)
async def activities(
    contact_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ActivityResponse:
    contact = await db.get(Contact, contact_id)
    if not contact or contact.workspace_id != tenant.workspace_id or not contact.bitrix_lead_id:
        raise NotFoundError("Контакт или Bitrix24 lead не найден")
    rows = await Bitrix24Client().list_activities(
        {"OWNER_ID": contact.bitrix_lead_id, "OWNER_TYPE_ID": 1}
    )
    return ActivityResponse(activities=rows)


@router.get("/sync-stats")
async def sync_stats(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    return await Bitrix24SyncService(db, tenant.workspace_id).stats()


@router.post("/setup-fields")
async def setup_fields(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> dict[str, int | str]:
    return await Bitrix24SyncService(db, tenant.workspace_id).setup_fields()
