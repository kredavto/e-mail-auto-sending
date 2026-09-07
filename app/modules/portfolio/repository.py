from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.portfolio.models import PortfolioCase


class PortfolioRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def list_all(self, published: bool = False) -> list[PortfolioCase]:
        q = select(PortfolioCase).where(PortfolioCase.workspace_id == self.workspace_id)
        if published:
            q = q.where(PortfolioCase.is_published.is_(True))
        return list((await self.db.scalars(q)).all())

    async def add(self, item: PortfolioCase) -> PortfolioCase:
        self.db.add(item)
        await self.db.flush()
        return item

    async def get(self, item_id: UUID) -> PortfolioCase | None:
        result = await self.db.scalars(
            select(PortfolioCase).where(
                PortfolioCase.id == item_id,
                PortfolioCase.workspace_id == self.workspace_id,
            )
        )
        return result.first()

    async def delete(self, item_id: UUID) -> bool:
        result = await self.db.execute(
            delete(PortfolioCase).where(
                PortfolioCase.id == item_id,
                PortfolioCase.workspace_id == self.workspace_id,
            )
        )
        return bool(getattr(result, "rowcount", 0))
