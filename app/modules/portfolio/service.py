from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.contacts.models import Contact
from app.modules.portfolio.models import PortfolioCase
from app.modules.portfolio.repository import PortfolioRepository
from app.modules.portfolio.schemas import CaseCreate, CaseMatch, CaseResponse, CaseUpdate


class PortfolioService:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.repo, self.workspace_id = PortfolioRepository(db, workspace_id), workspace_id

    async def create(self, data: CaseCreate) -> PortfolioCase:
        return await self.repo.add(
            PortfolioCase(workspace_id=self.workspace_id, **data.model_dump())
        )

    async def update(self, item_id: UUID, data: CaseUpdate) -> PortfolioCase:
        item = await self.repo.get(item_id)
        if not item:
            raise NotFoundError("Кейс не найден")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        return item

    async def match(self, contact: Contact) -> CaseMatch | None:
        best: tuple[PortfolioCase, float] | None = None
        for case in await self.repo.list_all(published=True):
            score = (
                1.0
                if case.industry == contact.industry and case.company_size == contact.company_size
                else (
                    0.7
                    if case.industry == contact.industry
                    else 0.5 if case.company_size == contact.company_size else 0.3
                )
            )
            if best is None or score > best[1]:
                best = (case, score)
        return CaseMatch(case=CaseResponse.model_validate(best[0]), score=best[1]) if best else None
