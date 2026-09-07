from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.sequences.repository import SequenceRepository
from app.modules.sequences.schemas import (
    SequenceCreate,
    SequenceResponse,
    SequenceUpdate,
    StepCreate,
    StepResponse,
    ValidationResponse,
)
from app.modules.sequences.service import SequenceService

router = APIRouter(prefix="/sequences", tags=["sequences"])


@router.get("", response_model=list[SequenceResponse])
async def list_sequences(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[SequenceResponse]:
    return [
        SequenceResponse.model_validate(i)
        for i in await SequenceRepository(db, tenant.workspace_id).list_all()
    ]


@router.post("", response_model=SequenceResponse, status_code=201)
async def create_sequence(
    data: SequenceCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SequenceResponse:
    return SequenceResponse.model_validate(
        await SequenceService(db, tenant.workspace_id).create(data)
    )


@router.patch("/{sequence_id}", response_model=SequenceResponse)
async def update_sequence(
    sequence_id: UUID,
    data: SequenceUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> SequenceResponse:
    return SequenceResponse.model_validate(
        await SequenceService(db, tenant.workspace_id).update(sequence_id, data)
    )


@router.delete("/{sequence_id}", status_code=204)
async def delete_sequence(
    sequence_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await SequenceRepository(db, tenant.workspace_id).delete(sequence_id):
        raise NotFoundError("Цепочка не найдена")
    return Response(status_code=204)


@router.get("/{sequence_id}/steps", response_model=list[StepResponse])
async def steps(
    sequence_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[StepResponse]:
    return [
        StepResponse.model_validate(i)
        for i in await SequenceRepository(db, tenant.workspace_id).steps(sequence_id)
    ]


@router.post("/{sequence_id}/steps", response_model=StepResponse, status_code=201)
async def add_step(
    sequence_id: UUID,
    data: StepCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> StepResponse:
    return StepResponse.model_validate(
        await SequenceService(db, tenant.workspace_id).add_step(sequence_id, data)
    )


@router.get("/{sequence_id}/validate", response_model=ValidationResponse)
async def validate(
    sequence_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ValidationResponse:
    return await SequenceService(db, tenant.workspace_id).validate(sequence_id)
