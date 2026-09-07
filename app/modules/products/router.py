from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TenantContext, get_tenant_context
from app.core.events import IntegrationEvent, publish_enterprise_event
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.modules.audit.service import AuditService
from app.modules.contacts.repository import ContactRepository
from app.modules.products.repository import ProductRepository
from app.modules.products.schemas import ProductCreate, ProductMatch, ProductResponse, ProductUpdate
from app.modules.products.service import ProductService
from app.shared.dto import MessageResponse

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductResponse])
async def list_products(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[ProductResponse]:
    return [
        ProductResponse.model_validate(i)
        for i in await ProductRepository(db, tenant.workspace_id).list_all()
    ]


@router.post("", response_model=ProductResponse, status_code=201)
async def create_product(
    data: ProductCreate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    row = await ProductService(db, tenant.workspace_id).create(data)
    await publish_enterprise_event(
        db,
        IntegrationEvent(
            workspace_id=tenant.workspace_id,
            actor_id=tenant.user.id,
            resource_type="product",
            resource_id=row.id,
            data={"name": row.name, "slug": row.slug},
            kind="product.created",
        ),
    )
    return ProductResponse.model_validate(row)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    item = await ProductRepository(db, tenant.workspace_id).get(product_id)
    if not item:
        raise NotFoundError("Направление не найдено")
    return ProductResponse.model_validate(item)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    data: ProductUpdate,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    return ProductResponse.model_validate(
        await ProductService(db, tenant.workspace_id).update(product_id, data)
    )


@router.delete("/{product_id}", status_code=204)
async def delete_product(
    product_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    deleted = await ProductRepository(db, tenant.workspace_id).delete(product_id)
    if deleted:
        await AuditService(db, tenant.workspace_id).log(
            "product.deleted",
            "product",
            user_id=tenant.user.id,
            resource_id=product_id,
        )
    return Response(status_code=204)


@router.get("/match/{contact_id}", response_model=list[ProductMatch])
async def match_products(
    contact_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> list[ProductMatch]:
    contact = await ContactRepository(db, tenant.workspace_id).get(contact_id)
    if not contact:
        raise NotFoundError("Контакт не найден")
    return await ProductService(db, tenant.workspace_id).match(contact)


@router.post("/seed/defaults", response_model=MessageResponse)
async def seed_defaults(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    count = await ProductService(db, tenant.workspace_id).load_defaults()
    return MessageResponse(message=f"Добавлено направлений: {count}")
