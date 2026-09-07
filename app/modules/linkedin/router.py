from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import AppError
from app.database import get_db
from app.modules.linkedin.models import LinkedInExport, LinkedInProfile
from app.modules.linkedin.schemas import (
    EnrichRequest,
    LeadGenSyncRequest,
    LinkedInProfileResponse,
    MatchedAudienceRequest,
)
from app.modules.linkedin.tasks import (
    create_linkedin_matched_audience,
    enrich_linkedin_emails,
    process_linkedin_export,
    sync_linkedin_lead_gen_forms,
)

router = APIRouter(prefix="/linkedin", tags=["linkedin"])
MAX_CSV_BYTES = 10 * 1024 * 1024


@router.post("/import-csv", status_code=202)
async def import_csv(
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    content = await file.read(MAX_CSV_BYTES + 1)
    if len(content) > MAX_CSV_BYTES:
        raise AppError("CSV превышает лимит 10 МБ")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError("CSV должен быть в UTF-8") from exc
    export = LinkedInExport(
        workspace_id=tenant.workspace_id, filename=file.filename or "linkedin.csv", status="pending"
    )
    db.add(export)
    await db.commit()
    task = process_linkedin_export.delay(str(tenant.workspace_id), str(export.id), text)
    return {"export_id": str(export.id), "task_id": str(task.id), "status": "pending"}


@router.get("/exports")
async def exports(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, object]]:
    rows = list(
        (
            await db.scalars(
                select(LinkedInExport)
                .where(LinkedInExport.workspace_id == tenant.workspace_id)
                .order_by(LinkedInExport.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return [
        {
            "id": str(row.id),
            "filename": row.filename,
            "status": row.status,
            "total_rows": row.total_rows,
            "imported_rows": row.imported_rows,
            "error_message": row.error_message,
        }
        for row in rows
    ]


@router.get("/profiles", response_model=list[LinkedInProfileResponse])
async def profiles(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[LinkedInProfile]:
    return list(
        (
            await db.scalars(
                select(LinkedInProfile)
                .where(LinkedInProfile.workspace_id == tenant.workspace_id)
                .order_by(LinkedInProfile.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )


@router.post("/enrich", status_code=202)
async def enrich(
    data: EnrichRequest, tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, str]:
    task = enrich_linkedin_emails.delay(
        str(tenant.workspace_id), [str(value) for value in data.profile_ids]
    )
    return {"task_id": str(task.id), "status": "queued"}


@router.post("/lead-gen-forms/sync", status_code=202)
async def sync_forms(
    data: LeadGenSyncRequest, tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, str]:
    task = sync_linkedin_lead_gen_forms.delay(str(tenant.workspace_id), data.ad_account_id)
    return {"task_id": str(task.id), "status": "queued"}


@router.post("/matched-audiences", status_code=202)
async def matched_audiences(
    data: MatchedAudienceRequest, _tenant: TenantContext = Depends(get_tenant_context)
) -> dict[str, str]:
    task = create_linkedin_matched_audience.delay(data.name, [str(email) for email in data.emails])
    return {"task_id": str(task.id), "status": "queued"}
