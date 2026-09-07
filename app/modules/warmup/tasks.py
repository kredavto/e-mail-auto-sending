import asyncio

from app.celery_app import celery_app


@celery_app.task(name="app.modules.warmup.tasks.advance_plans")  # type: ignore[untyped-decorator]
def advance_plans() -> dict[str, int]:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.domains.models import SendingDomain
    from app.modules.warmup.models import WarmupPlan
    from app.modules.warmup.service import WarmupService

    async def run() -> dict[str, int]:
        count = 0
        async with async_session_factory() as db:
            for plan in (
                await db.scalars(select(WarmupPlan).where(WarmupPlan.status == "active"))
            ).all():
                domain = await db.get(SendingDomain, plan.domain_id)
                if domain:
                    await WarmupService(db, domain.workspace_id).advance(plan)
                    count += 1
            await db.commit()
        return {"advanced": count}

    return asyncio.run(run())
