import asyncio
from datetime import UTC, datetime

from app.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.modules.scheduler.tasks.schedule_campaigns", queue="emails"
)
def schedule_campaigns() -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.scheduler.service import SchedulerService

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            dispatched = await SchedulerService(db, celery_app).dispatch_due(datetime.now(UTC))
            await db.commit()
            return {"dispatched": dispatched}

    return asyncio.run(run())
