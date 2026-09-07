from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.templates.models import Template, TemplateVersion


class TemplateRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id

    async def list_all(self, product_id: UUID | None = None) -> list[Template]:
        query = select(Template).where(Template.workspace_id == self.workspace_id)
        if product_id:
            query = query.where(Template.product_id == product_id)
        return list((await self.db.scalars(query.order_by(Template.updated_at.desc()))).all())

    async def get(self, template_id: UUID) -> Template | None:
        result = await self.db.scalars(
            select(Template).where(
                Template.id == template_id, Template.workspace_id == self.workspace_id
            )
        )
        return result.first()

    async def add(self, item: Template) -> Template:
        self.db.add(item)
        await self.db.flush()
        return item

    async def add_version(self, item: TemplateVersion) -> None:
        self.db.add(item)
        await self.db.flush()

    async def versions(self, template_id: UUID) -> list[TemplateVersion]:
        query = (
            select(TemplateVersion)
            .join(Template)
            .where(
                TemplateVersion.template_id == template_id,
                Template.workspace_id == self.workspace_id,
            )
            .order_by(TemplateVersion.version.desc())
        )
        return list((await self.db.scalars(query)).all())

    async def version(self, template_id: UUID, version: int) -> TemplateVersion | None:
        result = await self.db.scalars(
            select(TemplateVersion)
            .join(Template)
            .where(
                TemplateVersion.template_id == template_id,
                TemplateVersion.version == version,
                Template.workspace_id == self.workspace_id,
            )
        )
        return result.first()

    async def delete(self, template_id: UUID) -> bool:
        result = await self.db.execute(
            delete(Template).where(
                Template.id == template_id, Template.workspace_id == self.workspace_id
            )
        )
        return bool(getattr(result, "rowcount", 0))
