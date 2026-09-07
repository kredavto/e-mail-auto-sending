from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_upload.models import UploadedFile


class FileRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id

    async def add(self, item: UploadedFile) -> UploadedFile:
        self.db.add(item)
        await self.db.flush()
        return item

    async def get(self, file_id: UUID) -> UploadedFile | None:
        result = await self.db.scalars(
            select(UploadedFile).where(
                UploadedFile.id == file_id, UploadedFile.workspace_id == self.workspace_id
            )
        )
        return result.first()
