from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.email_validation.schemas import (
    ValidateBatchRequest,
    ValidateRequest,
    ValidationResponse,
)
from app.modules.email_validation.service import EmailValidationService

router = APIRouter(prefix="/validation", tags=["email-validation"])


@router.post("/validate", response_model=ValidationResponse)
async def validate(
    data: ValidateRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ValidationResponse:
    row = await EmailValidationService(db, tenant.workspace_id).validate(
        data.email, smtp_check=data.smtp_check
    )
    return ValidationResponse.model_validate(row)


@router.post("/validate-batch", response_model=list[ValidationResponse])
async def validate_batch(
    data: ValidateBatchRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[ValidationResponse]:
    service = EmailValidationService(db, tenant.workspace_id)
    rows = [
        await service.validate(email, smtp_check=data.smtp_check)
        for email in dict.fromkeys(data.emails)
    ]
    return [ValidationResponse.model_validate(row) for row in rows]


@router.get("/results/{email}", response_model=ValidationResponse)
async def result(
    email: str,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ValidationResponse:
    row = await EmailValidationService(db, tenant.workspace_id).latest(email)
    if not row:
        raise NotFoundError("Результат проверки не найден")
    return ValidationResponse.model_validate(row)


@router.get("/stats")
async def stats(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    return await EmailValidationService(db, tenant.workspace_id).stats()
