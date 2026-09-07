from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.editor.service import VARIABLE_RE, EditorService
from app.modules.quality.service import QualityChecker
from app.modules.templates.models import Template, TemplateVersion
from app.modules.templates.repository import TemplateRepository
from app.modules.templates.schemas import TemplateCreate, TemplateUpdate


class TemplateService:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.repo = TemplateRepository(db, workspace_id)
        self.workspace_id = workspace_id
        self.editor = EditorService()

    def _compiled(self, state: dict[str, object], subject: str) -> tuple[str, str, list[str], int]:
        html, text, variables, score, _ = self.editor.compile(state)
        variables = sorted(set(variables) | set(VARIABLE_RE.findall(subject)))
        score = QualityChecker().check(html, text, subject).score
        return html, text, variables, score

    async def create(self, data: TemplateCreate) -> Template:
        html, text, variables, score = self._compiled(data.editor_state, data.subject_template)
        item = Template(
            workspace_id=self.workspace_id,
            html_body=html,
            text_body=text,
            variables=variables,
            quality_score=score,
            **data.model_dump(),
        )
        await self.repo.add(item)
        await self._snapshot(item)
        return item

    async def update(self, template_id: UUID, data: TemplateUpdate) -> Template:
        item = await self.repo.get(template_id)
        if not item:
            raise NotFoundError("Шаблон не найден")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        item.version += 1
        item.html_body, item.text_body, item.variables, item.quality_score = self._compiled(
            item.editor_state, item.subject_template
        )
        await self._snapshot(item)
        return item

    async def rollback(self, template_id: UUID, version: int) -> Template:
        item = await self.repo.get(template_id)
        snapshot = await self.repo.version(template_id, version)
        if not item or not snapshot:
            raise NotFoundError("Версия шаблона не найдена")
        item.version += 1
        for field in (
            "subject_template",
            "editor_state",
            "html_body",
            "text_body",
            "variables",
            "quality_score",
        ):
            setattr(item, field, getattr(snapshot, field))
        await self._snapshot(item)
        return item

    async def _snapshot(self, item: Template) -> None:
        await self.repo.add_version(
            TemplateVersion(
                template_id=item.id,
                version=item.version,
                subject_template=item.subject_template,
                editor_state=item.editor_state,
                html_body=item.html_body,
                text_body=item.text_body,
                variables=item.variables,
                quality_score=item.quality_score,
            )
        )
