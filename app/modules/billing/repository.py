from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.models import Invoice, Subscription, UsageLog


class BillingRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def subscription(self, *, for_update: bool = False) -> Subscription | None:
        query = select(Subscription).where(Subscription.workspace_id == self.workspace_id)
        if for_update:
            query = query.with_for_update()
        return cast(Subscription | None, await self.db.scalar(query))

    async def usage(
        self, metric: str, period_start: datetime, *, for_update: bool = False
    ) -> UsageLog | None:
        query = select(UsageLog).where(
            UsageLog.workspace_id == self.workspace_id,
            UsageLog.metric == metric,
            UsageLog.period_start == period_start,
        )
        if for_update:
            query = query.with_for_update()
        return cast(UsageLog | None, await self.db.scalar(query))

    async def usage_period(self, period_start: datetime) -> list[UsageLog]:
        return list(
            (
                await self.db.scalars(
                    select(UsageLog).where(
                        UsageLog.workspace_id == self.workspace_id,
                        UsageLog.period_start == period_start,
                    )
                )
            ).all()
        )

    async def invoices(self) -> list[Invoice]:
        return list(
            (
                await self.db.scalars(
                    select(Invoice)
                    .where(Invoice.workspace_id == self.workspace_id)
                    .order_by(Invoice.created_at.desc())
                )
            ).all()
        )
