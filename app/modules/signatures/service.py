from typing import cast
from uuid import UUID

import bleach
from jinja2 import Environment, StrictUndefined, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.editor.service import CSS_SANITIZER
from app.modules.signatures.models import Signature
from app.modules.signatures.repository import SignatureRepository
from app.modules.signatures.schemas import SignatureCreate, SignatureUpdate


class SignatureService:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.repo, self.workspace_id = SignatureRepository(db, workspace_id), workspace_id

    async def create(self, data: SignatureCreate) -> Signature:
        values = data.model_dump()
        values["html_template"] = self._sanitize(data.html_template)
        return await self.repo.add(Signature(workspace_id=self.workspace_id, **values))

    @staticmethod
    def _sanitize(value: str) -> str:
        return cast(
            str,
            bleach.clean(
                value,
                tags=["p", "br", "strong", "em", "a", "img", "table", "tr", "td", "span"],
                attributes={
                    "*": ["style"],
                    "a": ["href"],
                    "img": ["src", "alt", "width", "height"],
                },
                css_sanitizer=CSS_SANITIZER,
                strip=True,
            ),
        )

    async def update(self, item_id: UUID, data: SignatureUpdate) -> Signature:
        item = await self.repo.get(item_id)
        if not item:
            raise NotFoundError("Подпись не найдена")
        changes = data.model_dump(exclude_unset=True)
        if changes.get("html_template"):
            changes["html_template"] = self._sanitize(str(changes["html_template"]))
        for field, value in changes.items():
            setattr(item, field, value)
        return item

    async def render(self, item_id: UUID, variables: dict[str, str]) -> str:
        item = await self.repo.get(item_id)
        if not item:
            raise NotFoundError("Подпись не найдена")
        env = Environment(autoescape=select_autoescape(default=True), undefined=StrictUndefined)
        return env.from_string(item.html_template).render(**variables)
