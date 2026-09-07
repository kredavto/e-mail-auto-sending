import asyncio

from app.celery_app import celery_app


@celery_app.task(name="app.modules.blacklists.tasks.check_all_domains")  # type: ignore[untyped-decorator]
def check_all_domains() -> dict[str, int]:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.blacklists.service import BlacklistService
    from app.modules.domains.models import SendingDomain

    async def run() -> dict[str, int]:
        checked = listed = 0
        async with async_session_factory() as db:
            domains = list((await db.scalars(select(SendingDomain))).all())
            for domain in domains:
                rows = await BlacklistService(db, domain.workspace_id).check(domain.id)
                checked += 1
                listed += sum(row.listed for row in rows)
            await db.commit()
        return {"domains_checked": checked, "listings": listed}

    return asyncio.run(run())
