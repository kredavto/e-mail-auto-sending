from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import (
    Notification,
    NotificationPreference,
    WebPushSubscription,
)


class NotificationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, row: Notification) -> Notification:
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_for_user(
        self, user_id: UUID, workspace_id: UUID, offset: int, limit: int, unread_only: bool = False
    ) -> tuple[list[Notification], int]:
        conditions = [
            Notification.user_id == user_id,
            Notification.workspace_id == workspace_id,
        ]
        if unread_only:
            conditions.append(Notification.is_read.is_(False))
        total = await self.db.scalar(
            select(func.count()).select_from(Notification).where(*conditions)
        )
        rows = await self.db.scalars(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows.all()), int(total or 0)

    async def get_for_user(
        self, notification_id: UUID, user_id: UUID, workspace_id: UUID
    ) -> Notification | None:
        return cast(
            Notification | None,
            await self.db.scalar(
                select(Notification).where(
                    Notification.id == notification_id,
                    Notification.user_id == user_id,
                    Notification.workspace_id == workspace_id,
                )
            ),
        )

    async def mark_all_read(self, user_id: UUID, workspace_id: UUID) -> int:
        from datetime import UTC, datetime

        result = await self.db.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.workspace_id == workspace_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def unread_count(self, user_id: UUID, workspace_id: UUID) -> int:
        value = await self.db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.workspace_id == workspace_id,
                Notification.is_read.is_(False),
            )
        )
        return int(value or 0)

    async def preference(self, user_id: UUID, workspace_id: UUID) -> NotificationPreference | None:
        return cast(
            NotificationPreference | None,
            await self.db.scalar(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id,
                    NotificationPreference.workspace_id == workspace_id,
                )
            ),
        )

    async def subscriptions(self, user_id: UUID) -> list[WebPushSubscription]:
        return list(
            (
                await self.db.scalars(
                    select(WebPushSubscription).where(
                        WebPushSubscription.user_id == user_id,
                        WebPushSubscription.is_active.is_(True),
                    )
                )
            ).all()
        )
