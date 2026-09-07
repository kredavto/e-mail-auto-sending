import asyncio
from datetime import date

from app.celery_app import celery_app


@celery_app.task(name="app.modules.analytics.tasks.aggregate_daily")  # type: ignore[untyped-decorator]
def aggregate_daily(day: str | None = None) -> dict[str, int]:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.analytics.service import AnalyticsService
    from app.modules.users.models import Workspace

    async def run() -> dict[str, int]:
        total = 0
        async with async_session_factory() as db:
            workspace_ids = list((await db.scalars(select(Workspace.id))).all())
            for workspace_id in workspace_ids:
                total += await AnalyticsService(db, workspace_id).aggregate_daily(
                    date.fromisoformat(day) if day else None
                )
            await db.commit()
        return {"aggregated": total}

    return asyncio.run(run())
