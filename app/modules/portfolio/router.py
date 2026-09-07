from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.contacts.repository import ContactRepository
from app.modules.portfolio.repository import PortfolioRepository
from app.modules.portfolio.schemas import CaseCreate, CaseMatch, CaseResponse, CaseUpdate
from app.modules.portfolio.service import PortfolioService

router = APIRouter(prefix="/portfolio/cases", tags=["portfolio"])


@router.get("", response_model=list[CaseResponse])
async def list_cases(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[CaseResponse]:
    return [
        CaseResponse.model_validate(i)
        for i in await PortfolioRepository(db, tenant.workspace_id).list_all()
    ]


@router.post("", response_model=CaseResponse, status_code=201)
async def create_case(
    data: CaseCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> CaseResponse:
    return CaseResponse.model_validate(await PortfolioService(db, tenant.workspace_id).create(data))


@router.patch("/{case_id}", response_model=CaseResponse)
async def update_case(
    case_id: UUID,
    data: CaseUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> CaseResponse:
    return CaseResponse.model_validate(
        await PortfolioService(db, tenant.workspace_id).update(case_id, data)
    )


@router.delete("/{case_id}", status_code=204)
async def delete_case(
    case_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await PortfolioRepository(db, tenant.workspace_id).delete(case_id):
        raise NotFoundError("Кейс не найден")
    return Response(status_code=204)


@router.get("/match/{contact_id}", response_model=CaseMatch | None)
async def match_case(
    contact_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> CaseMatch | None:
    contact = await ContactRepository(db, tenant.workspace_id).get(contact_id)
    if not contact:
        raise NotFoundError("Контакт не найден")
    return await PortfolioService(db, tenant.workspace_id).match(contact)
