from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import cast as sa_cast
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.webhooks.models import Webhook, WebhookDelivery


class WebhookRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def add(self, row: Webhook) -> Webhook:
        self.db.add(row)
        await self.db.flush()
        return row

    async def get(self, webhook_id: UUID) -> Webhook | None:
        return cast(
            Webhook | None,
            await self.db.scalar(
                select(Webhook).where(
                    Webhook.id == webhook_id, Webhook.workspace_id == self.workspace_id
                )
            ),
        )

    async def list_all(self) -> list[Webhook]:
        return list(
            (
                await self.db.scalars(
                    select(Webhook)
                    .where(Webhook.workspace_id == self.workspace_id)
                    .order_by(Webhook.created_at.desc())
                )
            ).all()
        )

    async def get_by_event(self, event_type: str) -> list[Webhook]:
        return list(
            (
                await self.db.scalars(
                    select(Webhook).where(
                        Webhook.workspace_id == self.workspace_id,
                        Webhook.is_active.is_(True),
                        Webhook.events.contains(sa_cast([event_type], JSONB)),
                    )
                )
            ).all()
        )

    async def deliveries(self, webhook_id: UUID, limit: int = 100) -> list[WebhookDelivery]:
        return list(
            (
                await self.db.scalars(
                    select(WebhookDelivery)
                    .where(WebhookDelivery.webhook_id == webhook_id)
                    .order_by(WebhookDelivery.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
