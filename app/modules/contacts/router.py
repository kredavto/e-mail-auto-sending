from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.events import IntegrationEvent, publish_enterprise_event
from app.core.pagination import Page, PageParams
from app.database import get_db
from app.modules.audit.service import AuditService
from app.modules.billing.service import BillingService
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import (
    BulkContactsCreate,
    BulkResult,
    ContactCreate,
    ContactResponse,
    ContactUpdate,
    SegmentCreate,
    SegmentResponse,
)
from app.modules.contacts.service import ContactService
from app.modules.file_upload.service import FileService

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=Page[ContactResponse])
async def list_contacts(
    pagination: PageParams = Depends(),
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Page[ContactResponse]:
    items, total = await ContactRepository(db, tenant.workspace_id).list_all(
        pagination.offset, pagination.page_size
    )
    return Page(
        items=[ContactResponse.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("", response_model=ContactResponse, status_code=201)
async def create_contact(
    data: ContactCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    await BillingService(db, tenant.workspace_id).check_limits("create_contact")
    row = await ContactService(db, tenant.workspace_id).create(data)
    await publish_enterprise_event(
        db,
        IntegrationEvent(
            workspace_id=tenant.workspace_id,
            actor_id=tenant.user.id,
            resource_type="contact",
            resource_id=row.id,
            data={"email": row.email},
            kind="contact.created",
        ),
    )
    return ContactResponse.model_validate(row)


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: UUID,
    data: ContactUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    return ContactResponse.model_validate(
        await ContactService(db, tenant.workspace_id).update(contact_id, data)
    )


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(
    contact_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    deleted = await ContactRepository(db, tenant.workspace_id).delete(contact_id)
    if deleted:
        await AuditService(db, tenant.workspace_id).log(
            "contact.deleted",
            "contact",
            user_id=tenant.user.id,
            resource_id=contact_id,
        )
    return Response(status_code=204)


@router.post("/bulk", response_model=BulkResult)
async def bulk(
    data: BulkContactsCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> BulkResult:
    await BillingService(db, tenant.workspace_id).check_limits(
        "create_contact", max(1, len(data.contacts))
    )
    result = await ContactService(db, tenant.workspace_id).bulk(data.contacts)
    if result.created:
        await publish_enterprise_event(
            db,
            IntegrationEvent(
                workspace_id=tenant.workspace_id,
                actor_id=tenant.user.id,
                resource_type="contact",
                data={"count": result.created},
                kind="contact.created",
            ),
        )
    return result


@router.post("/import", response_model=BulkResult)
async def import_contacts(
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> BulkResult:
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise ValueError("Максимальный размер файла 25 MB")
    _, rows = FileService.parse_content(file.filename or "contacts.csv", content)
    allowed = set(ContactCreate.model_fields)
    contacts: list[ContactCreate] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=2):
        try:
            contacts.append(
                ContactCreate.model_validate(
                    {key: value for key, value in row.items() if key in allowed}
                )
            )
        except ValueError as exc:
            errors.append(f"Строка {index}: {exc}")
    if contacts:
        await BillingService(db, tenant.workspace_id).check_limits("create_contact", len(contacts))
    result = await ContactService(db, tenant.workspace_id).bulk(contacts)
    result.errors.extend(errors)
    if result.created:
        await publish_enterprise_event(
            db,
            IntegrationEvent(
                workspace_id=tenant.workspace_id,
                actor_id=tenant.user.id,
                resource_type="contact",
                data={"count": result.created},
                kind="contact.created",
            ),
        )
    return result


@router.get("/export")
async def export(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> Response:
    content = await ContactService(db, tenant.workspace_id).export_csv()
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )


@router.post("/deduplicate", response_model=BulkResult)
async def deduplicate() -> BulkResult:
    return BulkResult(created=0, skipped=0, errors=[])


@router.get("/segments", response_model=list[SegmentResponse])
async def segments(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[SegmentResponse]:
    return [
        SegmentResponse.model_validate(i)
        for i in await ContactRepository(db, tenant.workspace_id).list_segments()
    ]


@router.post("/segments", response_model=SegmentResponse, status_code=201)
async def create_segment(
    data: SegmentCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SegmentResponse:
    return SegmentResponse.model_validate(
        await ContactService(db, tenant.workspace_id).create_segment(data)
    )
