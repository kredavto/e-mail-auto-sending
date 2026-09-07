from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sender.models import EmailMessage


class MessageRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def add(self, item: EmailMessage) -> EmailMessage:
        self.db.add(item)
        await self.db.flush()
        return item

    async def get(self, message_id: UUID) -> EmailMessage | None:
        item = await self.db.get(EmailMessage, message_id)
        return item if item and item.workspace_id == self.workspace_id else None
