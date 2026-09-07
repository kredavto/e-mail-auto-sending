from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sequences.models import Sequence, SequenceStep


class SequenceRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def list_all(self) -> list[Sequence]:
        return list(
            (
                await self.db.scalars(
                    select(Sequence).where(Sequence.workspace_id == self.workspace_id)
                )
            ).all()
        )

    async def get(self, item_id: UUID) -> Sequence | None:
        result = await self.db.scalars(
            select(Sequence).where(
                Sequence.id == item_id, Sequence.workspace_id == self.workspace_id
            )
        )
        return result.first()

    async def add(self, item: Sequence) -> Sequence:
        self.db.add(item)
        await self.db.flush()
        return item

    async def add_step(self, item: SequenceStep) -> SequenceStep:
        self.db.add(item)
        await self.db.flush()
        return item

    async def steps(self, sequence_id: UUID) -> list[SequenceStep]:
        return list(
            (
                await self.db.scalars(
                    select(SequenceStep)
                    .join(Sequence)
                    .where(
                        SequenceStep.sequence_id == sequence_id,
                        Sequence.workspace_id == self.workspace_id,
                    )
                    .order_by(SequenceStep.position)
                )
            ).all()
        )

    async def delete(self, item_id: UUID) -> bool:
        result = await self.db.execute(
            delete(Sequence).where(
                Sequence.id == item_id, Sequence.workspace_id == self.workspace_id
            )
        )
        return bool(getattr(result, "rowcount", 0))
