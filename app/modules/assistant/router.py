from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.pagination import Page, PageParams
from app.database import get_db
from app.modules.assistant.models import AssistantRun
from app.modules.assistant.schemas import (
    ActionRequest,
    AskRequest,
    CampaignDraftRequest,
    ConfirmRequest,
    RunResponse,
)
from app.modules.assistant.service import AssistantService
from app.modules.campaigns.schemas import CampaignResponse
from app.modules.contacts.models import Contact
from app.modules.contacts.schemas import ContactResponse

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/contacts", response_model=Page[ContactResponse])
async def eligible_contacts(
    search: str = Query(default="", max_length=200),
    pagination: PageParams = Depends(),
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    filters = [
        Contact.workspace_id == tenant.workspace_id,
        Contact.is_unsubscribed.is_(False),
        Contact.has_replied.is_(False),
        Contact.status.notin_(["bounced", "meeting_booked"]),
    ]
    if search.strip():
        filters.append(
            or_(
                *(
                    field.icontains(search.strip(), autoescape=True)
                    for field in (Contact.email, Contact.full_name, Contact.company)
                )
            )
        )
    total = await db.scalar(select(func.count()).select_from(Contact).where(*filters))
    rows = (
        await db.scalars(
            select(Contact)
            .where(*filters)
            .order_by(Contact.created_at.desc(), Contact.id)
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
    ).all()
    return Page(
        items=[ContactResponse.model_validate(c) for c in rows],
        total=total or 0,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/context")
async def context(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
):
    return await AssistantService(db, tenant).context()


@router.post("/runs", response_model=RunResponse)
async def ask(
    data: AskRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    return await AssistantService(db, tenant).ask(data)


@router.get("/runs", response_model=list[RunResponse])
async def history(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
):
    return (
        await db.scalars(
            select(AssistantRun)
            .where(
                AssistantRun.workspace_id == tenant.workspace_id,
                AssistantRun.user_id == tenant.user.id,
            )
            .order_by(AssistantRun.created_at.desc())
            .limit(30)
        )
    ).all()


@router.get("/runs/{run_id}", response_model=RunResponse)
async def retrieve(
    run_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    return await AssistantService(db, tenant).get_run(run_id)


@router.post("/runs/{run_id}/confirm", response_model=RunResponse)
async def confirm(
    run_id: UUID,
    data: ConfirmRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    return await AssistantService(db, tenant).confirm(run_id)


@router.post("/campaigns/{campaign_id}/propose", response_model=RunResponse)
async def propose(
    campaign_id: UUID,
    data: ActionRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    return await AssistantService(db, tenant).prepare_action(campaign_id, data)


@router.post("/campaigns", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    data: CampaignDraftRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    return await AssistantService(db, tenant).create_campaign(data)
