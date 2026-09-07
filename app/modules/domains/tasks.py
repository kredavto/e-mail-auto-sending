import asyncio

from app.celery_app import celery_app


@celery_app.task(name="app.modules.domains.tasks.verify_all_domains")  # type: ignore[untyped-decorator]
def verify_all_domains() -> dict[str, int]:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.domains.models import SendingDomain
    from app.modules.domains.service import DomainService

    async def run() -> dict[str, int]:
        checked = verified = 0
        async with async_session_factory() as db:
            for domain in (await db.scalars(select(SendingDomain))).all():
                await DomainService(db, domain.workspace_id).verify(domain.id)
                checked += 1
                verified += domain.status == "verified"
            await db.commit()
        return {"checked": checked, "verified": verified}

    return asyncio.run(run())
