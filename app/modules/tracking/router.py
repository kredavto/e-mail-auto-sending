import base64
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.tracking.service import TrackingService
from app.shared.dto import MessageResponse

router = APIRouter(tags=["tracking"])
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@router.get("/track/open/{message_id}.png", include_in_schema=False)
async def open_pixel(message_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    await TrackingService(db).record(message_id, "open")
    return Response(
        PIXEL,
        media_type="image/png",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/track/click/{message_id}", include_in_schema=False)
async def click(
    message_id: UUID, url: str = Query(), db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    try:
        destination = base64.urlsafe_b64decode(url + "=" * (-len(url) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        destination = "https://example.com"
    if not destination.startswith(("http://", "https://")):
        destination = "https://example.com"
    await TrackingService(db).record(message_id, "click", {"url": destination})
    return RedirectResponse(destination, status_code=302)


@router.get("/unsubscribe/preview", include_in_schema=False)
async def unsubscribe_preview() -> Response:
    return Response(
        "Это предпросмотр ссылки отписки. В отправленном письме ссылка будет персональной. "
        "Сейчас никто не отписан от рассылки.",
        media_type="text/plain",
        headers={"Cache-Control": "no-store"},
    )


@router.api_route("/unsubscribe/{message_id}", methods=["GET", "POST"], include_in_schema=False)
async def unsubscribe(message_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    accepted = await TrackingService(db).unsubscribe(message_id)
    text = "Вы отписаны от рассылки" if accepted else "Ссылка недействительна"
    return Response(
        text,
        status_code=200 if accepted else 404,
        media_type="text/plain",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/tracking/meeting/{contact_id}", response_model=MessageResponse)
async def meeting_booked(
    contact_id: UUID,
    campaign_id: UUID | None = None,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await TrackingService(db).record_meeting(tenant.workspace_id, contact_id, campaign_id)
    return MessageResponse(message="Встреча зарегистрирована")
