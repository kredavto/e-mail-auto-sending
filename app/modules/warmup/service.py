import math
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.domains.models import SendingDomain
from app.modules.warmup.models import WarmupPlan
from app.modules.warmup.schemas import WarmupStart


class WarmupService:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def _domain(self, domain_id: UUID) -> SendingDomain:
        domain = await self.db.scalar(
            select(SendingDomain).where(
                SendingDomain.id == domain_id, SendingDomain.workspace_id == self.workspace_id
            )
        )
        if not domain:
            raise NotFoundError("Домен не найден")
        return domain

    async def get(self, domain_id: UUID) -> WarmupPlan:
        await self._domain(domain_id)
        plan = await self.db.scalar(select(WarmupPlan).where(WarmupPlan.domain_id == domain_id))
        if not plan:
            raise NotFoundError("План прогрева не найден")
        return plan

    async def start(self, data: WarmupStart) -> WarmupPlan:
        domain = await self._domain(data.domain_id)
        existing = await self.db.scalar(
            select(WarmupPlan).where(WarmupPlan.domain_id == data.domain_id)
        )
        if existing and existing.status == "active":
            raise ConflictError("Прогрев уже активен")
        target = min(data.target_daily_limit or domain.daily_limit, domain.daily_limit)
        if existing:
            existing.start_date, existing.current_daily_limit = date.today(), min(20, target)
            existing.target_daily_limit, existing.increment_percent = target, data.increment_percent
            existing.status, existing.provider = "active", data.provider
            return existing
        plan = WarmupPlan(
            domain_id=domain.id,
            start_date=date.today(),
            current_daily_limit=min(20, target),
            target_daily_limit=target,
            increment_percent=data.increment_percent,
            status="active",
            provider=data.provider,
        )
        self.db.add(plan)
        await self.db.flush()
        return plan

    async def pause(self, domain_id: UUID) -> WarmupPlan:
        plan = await self.get(domain_id)
        if plan.status != "active":
            raise ConflictError("Прогрев не активен")
        plan.status = "paused"
        return plan

    async def complete(self, domain_id: UUID) -> WarmupPlan:
        plan = await self.get(domain_id)
        plan.current_daily_limit, plan.status = plan.target_daily_limit, "completed"
        return plan

    @staticmethod
    def limit_on_day(plan: WarmupPlan, day_number: int) -> int:
        if day_number <= 1:
            return min(20, plan.target_daily_limit)
        return min(
            plan.target_daily_limit,
            math.ceil(20 * ((1 + plan.increment_percent) ** (day_number - 1))),
        )

    async def advance(self, plan: WarmupPlan, today: date | None = None) -> WarmupPlan:
        if plan.status != "active":
            return plan
        day_number = max(1, ((today or date.today()) - plan.start_date).days + 1)
        plan.current_daily_limit = self.limit_on_day(plan, day_number)
        if plan.current_daily_limit >= plan.target_daily_limit:
            plan.status = "completed"
        return plan

    async def schedule(self, domain_id: UUID) -> list[dict[str, object]]:
        plan = await self.get(domain_id)
        rows = []
        for index in range(365):
            limit = self.limit_on_day(plan, index + 1)
            rows.append(
                {
                    "day": index + 1,
                    "date": (plan.start_date + timedelta(days=index)).isoformat(),
                    "daily_limit": limit,
                }
            )
            if limit >= plan.target_daily_limit:
                break
        return rows
