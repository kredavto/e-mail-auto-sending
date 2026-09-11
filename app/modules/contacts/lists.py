from uuid import UUID

from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.contacts.models import Contact, Segment


def list_tag(list_id: UUID) -> str:
    return f"contact-list:{list_id}"


class ContactLists:
    """Named, tenant-scoped contact sets using existing segments and multi-valued tags."""

    def __init__(self, db: AsyncSession, workspace_id: UUID):
        self.db, self.workspace_id = db, workspace_id

    async def get(self, list_id: UUID) -> Segment:
        row = await self.db.scalar(
            select(Segment).where(
                Segment.id == list_id,
                Segment.workspace_id == self.workspace_id,
                Segment.filters["kind"].astext == "contact_list",
            )
        )
        if row is None:
            raise NotFoundError("База контактов не найдена")
        return row

    async def all(self) -> list[Segment]:
        return list(
            (
                await self.db.scalars(
                    select(Segment)
                    .where(
                        Segment.workspace_id == self.workspace_id,
                        Segment.filters["kind"].astext == "contact_list",
                    )
                    .order_by(Segment.created_at.desc(), Segment.id)
                )
            ).all()
        )

    async def create(self, name: str, include_existing: bool = False) -> Segment:
        row = Segment(workspace_id=self.workspace_id, name=name, filters={"kind": "contact_list"})
        self.db.add(row)
        await self.db.flush()
        if include_existing:
            await self.attach(row.id)
        return row

    async def attach(self, list_id: UUID, emails: list[str] | None = None) -> None:
        tag = list_tag(list_id)
        statement = update(Contact).where(
            Contact.workspace_id == self.workspace_id,
            ~Contact.tags.contains([tag]),
        )
        if emails is not None:
            statement = statement.where(Contact.email.in_(emails))
        await self.db.execute(
            statement.values(tags=Contact.tags.op("||")(cast([tag], JSONB))).execution_options(
                synchronize_session=False
            )
        )
