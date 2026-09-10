from asyncio import to_thread
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.database import get_db
from app.modules.contacts.schemas import BulkResult, ContactCreate
from app.modules.contacts.service import ContactService
from app.modules.file_upload.images import MAX_IMAGE_BYTES, EmailImageService
from app.modules.file_upload.schemas import FileResponse, ParseRequest, PreviewResponse
from app.modules.file_upload.service import FileService

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/images", status_code=201)
async def upload_email_image(
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, object]:
    body = await file.read(MAX_IMAGE_BYTES + 1)
    return await EmailImageService().upload(body, tenant.workspace_id)


@router.get("/images/{filename}")
async def email_image(filename: str) -> Response:
    # Deliberately public: email recipients cannot authenticate to this app.
    # Only random email-image names are accepted; never private uploaded files.
    body = await to_thread(EmailImageService().download, filename)
    return Response(
        content=body,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/upload", response_model=FileResponse, status_code=201)
async def upload(
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    body = await file.read()
    if len(body) > 25 * 1024 * 1024:
        raise ValueError("Максимальный размер файла 25 MB")
    item = await FileService(db, tenant.workspace_id).upload(
        file.filename or "upload.csv", file.content_type or "application/octet-stream", body
    )
    return FileResponse.model_validate(item)


@router.get("/{file_id}/preview", response_model=PreviewResponse)
async def preview(
    file_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> PreviewResponse:
    return await FileService(db, tenant.workspace_id).preview(file_id)


@router.post("/{file_id}/parse", response_model=BulkResult)
async def parse(
    file_id: UUID,
    _data: ParseRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> BulkResult:
    file_service = FileService(db, tenant.workspace_id)
    item, rows = await file_service.rows(file_id)
    contacts: list[ContactCreate] = []
    errors: list[str] = []
    for index, row in enumerate(rows[_data.skip_rows :], start=_data.skip_rows + 2):
        values = {
            target: row.get(source)
            for source, target in _data.mapping.items()
            if row.get(source) not in (None, "")
        }
        values.setdefault("source", f"file:{item.id}")
        try:
            contacts.append(ContactCreate.model_validate(values))
        except ValueError as exc:
            errors.append(f"Строка {index}: {exc}")
    result = await ContactService(db, tenant.workspace_id).bulk(contacts)
    result.errors.extend(errors)
    item.status = "parsed"
    return result
