from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tracking.models import TrackingEvent


class TrackingRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, item: TrackingEvent) -> TrackingEvent:
        self.db.add(item)
        await self.db.flush()
        return item
