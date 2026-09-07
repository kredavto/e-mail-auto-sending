import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dependencies import TenantContext, get_tenant_context
from app.core.security import decode_token
from app.database import async_session_factory, get_db
from app.modules.auth.models import AuthSession
from app.modules.notifications.models import WebPushSubscription
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import (
    NotificationPage,
    NotificationResponse,
    PreferenceResponse,
    PreferenceUpdate,
    UnreadCount,
    WebPushSubscriptionCreate,
)
from app.modules.notifications.service import NotificationService
from app.modules.users.models import User, WorkspaceMember
from app.shared.dto import MessageResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    unread_only: bool = False,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> NotificationPage:
    rows, total = await NotificationRepository(db).list_for_user(
        tenant.user.id, tenant.workspace_id, (page - 1) * page_size, page_size, unread_only
    )
    return NotificationPage(
        items=[NotificationResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    row = await NotificationService(db, tenant.workspace_id, tenant.user.id).mark_read(
        notification_id
    )
    return NotificationResponse.model_validate(row)


@router.post("/read-all", response_model=MessageResponse)
async def mark_all_read(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    count = await NotificationRepository(db).mark_all_read(tenant.user.id, tenant.workspace_id)
    return MessageResponse(message=f"Прочитано уведомлений: {count}")


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> UnreadCount:
    return UnreadCount(
        count=await NotificationRepository(db).unread_count(tenant.user.id, tenant.workspace_id)
    )


@router.put("/preferences", response_model=PreferenceResponse)
async def update_preferences(
    data: PreferenceUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> PreferenceResponse:
    row = await NotificationService(db, tenant.workspace_id, tenant.user.id).update_preferences(
        data
    )
    return PreferenceResponse.model_validate(row)


@router.post("/webpush-subscriptions", status_code=201)
async def subscribe_webpush(
    data: WebPushSubscriptionCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    row = await NotificationService(db, tenant.workspace_id, tenant.user.id).subscribe_webpush(data)
    return {"id": row.id, "endpoint": row.endpoint, "is_active": row.is_active}


@router.delete("/webpush-subscriptions/{subscription_id}", response_model=MessageResponse)
async def unsubscribe_webpush(
    subscription_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    row = await db.scalar(
        select(WebPushSubscription).where(
            WebPushSubscription.id == subscription_id,
            WebPushSubscription.user_id == tenant.user.id,
        )
    )
    if row:
        row.is_active = False
    return MessageResponse(message="Web Push подписка отключена")


async def _authenticate_ws(token: str, workspace_id: UUID) -> UUID | None:
    try:
        payload = decode_token(token, "access")
        user_id, session_id = UUID(payload["sub"]), UUID(payload["sid"])
    except Exception:
        return None
    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        session = await db.get(AuthSession, session_id)
        member = await db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        if not user or not user.is_active or not session or session.revoked_at or not member:
            return None
    return user_id


def _websocket_credentials(websocket: WebSocket) -> tuple[str | None, str | None, str | None]:
    authorization = websocket.headers.get("authorization", "")
    if authorization.casefold().startswith("bearer "):
        return authorization[7:].strip(), None, "authorization"
    cookie_token = websocket.cookies.get("access_token")
    if cookie_token:
        return cookie_token, None, "cookie"
    protocols = [
        value.strip()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    ]
    for index, protocol in enumerate(protocols):
        if protocol.casefold() == "bearer" and index + 1 < len(protocols):
            return protocols[index + 1], "bearer", "subprotocol"
    return None, None, None


def _cookie_origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    return bool(origin and origin in get_settings().cors_origins)


@router.websocket("/ws")
async def notifications_ws(websocket: WebSocket, workspace_id: UUID) -> None:
    token, accepted_protocol, source = _websocket_credentials(websocket)
    if not token or (source == "cookie" and not _cookie_origin_allowed(websocket)):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id = await _authenticate_ws(token, workspace_id)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept(subprotocol=accepted_protocol)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    channel = f"user:{user_id}:notifications"
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            payload = json.loads(message["data"])
            if payload.get("workspace_id") == str(workspace_id):
                await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis.aclose()
