from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.sequences.models import Sequence, SequenceStep
from app.modules.sequences.repository import SequenceRepository
from app.modules.sequences.schemas import (
    SequenceCreate,
    SequenceUpdate,
    StepCreate,
    ValidationResponse,
)


class SequenceService:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.repo, self.workspace_id = SequenceRepository(db, workspace_id), workspace_id

    async def create(self, data: SequenceCreate) -> Sequence:
        return await self.repo.add(Sequence(workspace_id=self.workspace_id, **data.model_dump()))

    async def update(self, sequence_id: UUID, data: SequenceUpdate) -> Sequence:
        sequence = await self.repo.get(sequence_id)
        if not sequence:
            raise NotFoundError("Цепочка не найдена")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(sequence, field, value)
        return sequence

    async def add_step(self, sequence_id: UUID, data: StepCreate) -> SequenceStep:
        if not await self.repo.get(sequence_id):
            raise NotFoundError("Цепочка не найдена")
        return await self.repo.add_step(SequenceStep(sequence_id=sequence_id, **data.model_dump()))

    async def validate(self, sequence_id: UUID) -> ValidationResponse:
        sequence = await self.repo.get(sequence_id)
        if not sequence:
            raise NotFoundError("Цепочка не найдена")
        steps = await self.repo.steps(sequence_id)
        errors: list[str] = []
        if not steps:
            errors.append("Цепочка не содержит шагов")
        positions = [step.position for step in steps]
        if positions != list(range(len(steps))):
            errors.append("Позиции шагов должны идти от 0 без пропусков")
        for step in steps:
            if step.step_type == "email" and not step.template_id:
                errors.append(f"Шаг {step.position}: не указан шаблон")
        window = sequence.send_window
        if not window.get("days") or not window.get("hours"):
            errors.append("Некорректное окно отправки")
        return ValidationResponse(valid=not errors, errors=errors)
