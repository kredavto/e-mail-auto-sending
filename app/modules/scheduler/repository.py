from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.campaigns.models import Campaign, CampaignContact


class SchedulerRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID | None = None) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def due(self, now: datetime, limit: int = 1000) -> list[CampaignContact]:
        query = (
            select(CampaignContact)
            .join(Campaign)
            .where(
                Campaign.status == "running",
                CampaignContact.status == "active",
                CampaignContact.next_send_at <= now,
            )
        )
        if self.workspace_id:
            query = query.where(Campaign.workspace_id == self.workspace_id)
        return list(
            (await self.db.scalars(query.with_for_update(skip_locked=True).limit(limit))).all()
        )

    async def upcoming(self, now: datetime, limit: int = 100) -> list[CampaignContact]:
        query = (
            select(CampaignContact)
            .join(Campaign)
            .where(
                Campaign.status == "running",
                CampaignContact.status == "active",
                CampaignContact.next_send_at >= now,
            )
        )
        if self.workspace_id:
            query = query.where(Campaign.workspace_id == self.workspace_id)
        return list(
            (await self.db.scalars(query.order_by(CampaignContact.next_send_at).limit(limit))).all()
        )
