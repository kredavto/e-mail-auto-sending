from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.database import get_db
from app.modules.webhooks.repository import WebhookRepository
from app.modules.webhooks.schemas import (
    WebhookCreate,
    WebhookCreated,
    WebhookDeliveryResponse,
    WebhookResponse,
    WebhookUpdate,
)
from app.modules.webhooks.service import WebhookDispatcher, WebhookService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def require_webhook_admin(tenant: TenantContext) -> None:
    if tenant.role not in {"owner", "admin"}:
        raise PermissionDeniedError("Управление вебхуками доступно владельцу и администраторам")


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[WebhookResponse]:
    require_webhook_admin(tenant)
    return [
        WebhookResponse.model_validate(row)
        for row in await WebhookRepository(db, tenant.workspace_id).list_all()
    ]


@router.post("", response_model=WebhookCreated, status_code=201)
async def create_webhook(
    data: WebhookCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> WebhookCreated:
    require_webhook_admin(tenant)
    row, secret = await WebhookService(db, tenant.workspace_id).create(data)
    response = WebhookResponse.model_validate(row).model_dump()
    return WebhookCreated(**response, secret=secret)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: UUID,
    data: WebhookUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    require_webhook_admin(tenant)
    return WebhookResponse.model_validate(
        await WebhookService(db, tenant.workspace_id).update(webhook_id, data)
    )


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    require_webhook_admin(tenant)
    await WebhookService(db, tenant.workspace_id).delete(webhook_id)
    return Response(status_code=204)


@router.post("/{webhook_id}/test", response_model=WebhookDeliveryResponse, status_code=202)
async def test_webhook(
    webhook_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> WebhookDeliveryResponse:
    require_webhook_admin(tenant)
    webhook = await WebhookRepository(db, tenant.workspace_id).get(webhook_id)
    if not webhook:
        raise NotFoundError("Вебхук не найден")
    dispatcher = WebhookDispatcher(db, tenant.workspace_id)
    event_id = uuid4()
    delivery = await dispatcher.dispatch(
        webhook.events[0], {"test": True, "webhook_id": str(webhook.id)}, event_id
    )
    # Dispatch() targets every subscriber; pick the explicitly tested webhook.
    row = next(item for item in delivery if item.webhook_id == webhook.id)
    return WebhookDeliveryResponse.model_validate(row)


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryResponse])
async def list_deliveries(
    webhook_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookDeliveryResponse]:
    require_webhook_admin(tenant)
    repo = WebhookRepository(db, tenant.workspace_id)
    if not await repo.get(webhook_id):
        raise NotFoundError("Вебхук не найден")
    return [
        WebhookDeliveryResponse.model_validate(row)
        for row in await repo.deliveries(webhook_id, limit)
    ]
