from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.queue.models import FailedTask


class QueueRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def list_failed(self) -> list[FailedTask]:
        return list(
            (
                await self.db.scalars(
                    select(FailedTask).where(
                        FailedTask.workspace_id == self.workspace_id, FailedTask.status == "failed"
                    )
                )
            ).all()
        )

    async def get(self, item_id: UUID) -> FailedTask | None:
        result = await self.db.scalars(
            select(FailedTask).where(
                FailedTask.id == item_id, FailedTask.workspace_id == self.workspace_id
            )
        )
        return result.first()
