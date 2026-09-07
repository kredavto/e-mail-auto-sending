from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.signatures.models import Signature


class SignatureRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def list_all(self) -> list[Signature]:
        return list(
            (
                await self.db.scalars(
                    select(Signature).where(Signature.workspace_id == self.workspace_id)
                )
            ).all()
        )

    async def get(self, item_id: UUID) -> Signature | None:
        result = await self.db.scalars(
            select(Signature).where(
                Signature.id == item_id, Signature.workspace_id == self.workspace_id
            )
        )
        return result.first()

    async def add(self, item: Signature) -> Signature:
        self.db.add(item)
        await self.db.flush()
        return item

    async def delete(self, item_id: UUID) -> bool:
        result = await self.db.execute(
            delete(Signature).where(
                Signature.id == item_id, Signature.workspace_id == self.workspace_id
            )
        )
        return bool(getattr(result, "rowcount", 0))
