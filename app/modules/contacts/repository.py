from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.lists import list_tag
from app.modules.contacts.models import Contact, Segment


class ContactRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id

    async def list_all(
        self, offset: int = 0, limit: int = 50, list_id: UUID | None = None
    ) -> tuple[list[Contact], int]:
        filters = [Contact.workspace_id == self.workspace_id]
        if list_id:
            filters.append(Contact.tags.contains([list_tag(list_id)]))
        base = select(Contact).where(*filters)
        items = list(
            (
                await self.db.scalars(
                    base.order_by(Contact.created_at.desc()).offset(offset).limit(limit)
                )
            ).all()
        )
        total = await self.db.scalar(select(func.count()).select_from(Contact).where(*filters))
        return items, int(total or 0)

    async def get(self, contact_id: UUID) -> Contact | None:
        result = await self.db.scalars(
            select(Contact).where(
                Contact.id == contact_id, Contact.workspace_id == self.workspace_id
            )
        )
        return result.first()

    async def by_email(self, email: str) -> Contact | None:
        result = await self.db.scalars(
            select(Contact).where(Contact.email == email, Contact.workspace_id == self.workspace_id)
        )
        return result.first()

    async def add(self, contact: Contact) -> Contact:
        self.db.add(contact)
        await self.db.flush()
        return contact

    async def delete(self, contact_id: UUID) -> bool:
        result = await self.db.execute(
            delete(Contact).where(
                Contact.id == contact_id, Contact.workspace_id == self.workspace_id
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def add_segment(self, segment: Segment) -> Segment:
        self.db.add(segment)
        await self.db.flush()
        return segment

    async def list_segments(self) -> list[Segment]:
        return list(
            (
                await self.db.scalars(
                    select(Segment).where(Segment.workspace_id == self.workspace_id)
                )
            ).all()
        )
