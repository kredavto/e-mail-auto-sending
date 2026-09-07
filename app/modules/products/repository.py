from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import Product


class ProductRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id

    async def list_all(self, active_only: bool = False) -> list[Product]:
        query = select(Product).where(Product.workspace_id == self.workspace_id)
        if active_only:
            query = query.where(Product.is_active.is_(True))
        return list((await self.db.scalars(query.order_by(Product.name))).all())

    async def get(self, product_id: UUID) -> Product | None:
        result = await self.db.scalars(
            select(Product).where(
                Product.id == product_id, Product.workspace_id == self.workspace_id
            )
        )
        return result.first()

    async def by_slug(self, slug: str) -> Product | None:
        result = await self.db.scalars(
            select(Product).where(Product.slug == slug, Product.workspace_id == self.workspace_id)
        )
        return result.first()

    async def add(self, product: Product) -> Product:
        self.db.add(product)
        await self.db.flush()
        return product

    async def delete(self, product_id: UUID) -> bool:
        result = await self.db.execute(
            delete(Product).where(
                Product.id == product_id, Product.workspace_id == self.workspace_id
            )
        )
        return bool(getattr(result, "rowcount", 0))
