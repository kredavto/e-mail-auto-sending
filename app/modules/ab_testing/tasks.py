import asyncio
from uuid import UUID

from app.celery_app import celery_app


@celery_app.task(name="app.modules.ab_testing.tasks.update_metrics")  # type: ignore[untyped-decorator]
def update_metrics(test_id: str | None = None) -> dict[str, int]:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.ab_testing.models import ABTest
    from app.modules.ab_testing.service import ABTestingService

    async def run() -> dict[str, int]:
        updated = 0
        async with async_session_factory() as db:
            query = select(ABTest).where(ABTest.status == "running")
            if test_id:
                query = query.where(ABTest.id == UUID(test_id))
            for item in (await db.scalars(query)).all():
                await ABTestingService(db, item.workspace_id).update_metrics(item.id)
                updated += 1
            await db.commit()
        return {"updated": updated}

    return asyncio.run(run())
