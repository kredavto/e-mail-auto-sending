from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.campaigns.models import Campaign, CampaignContact


class CampaignRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def list_all(self) -> list[Campaign]:
        return list(
            (
                await self.db.scalars(
                    select(Campaign)
                    .where(Campaign.workspace_id == self.workspace_id)
                    .order_by(Campaign.created_at.desc())
                )
            ).all()
        )

    async def get(self, item_id: UUID) -> Campaign | None:
        result = await self.db.scalars(
            select(Campaign).where(
                Campaign.id == item_id, Campaign.workspace_id == self.workspace_id
            )
        )
        return result.first()

    async def add(self, item: Campaign) -> Campaign:
        self.db.add(item)
        await self.db.flush()
        return item

    async def add_contacts(self, rows: list[CampaignContact]) -> None:
        self.db.add_all(rows)
        await self.db.flush()

    async def delete(self, item_id: UUID) -> bool:
        result = await self.db.execute(
            delete(Campaign).where(
                Campaign.id == item_id,
                Campaign.workspace_id == self.workspace_id,
                Campaign.status == "draft",
            )
        )
        return bool(getattr(result, "rowcount", 0))
