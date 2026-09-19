import asyncio

from sqlalchemy import text

from app.celery_app import celery_app


@celery_app.task(name="app.modules.contact_storage.tasks.sync_contacts", queue="enrichment")
def sync_contacts() -> dict:
    from app.database import async_session_factory
    from app.modules.contact_storage.service import ContactStorage

    async def run():
        async with async_session_factory() as db:
            # Stable source snapshot; one sync at a time even with multiple beat instances.
            await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            locked = await db.scalar(text("SELECT pg_try_advisory_xact_lock(726194315)"))
            if not locked:
                return {"status": "already_running"}
            result = await ContactStorage(db).sync_all()
            await db.commit()
            return result

    return asyncio.run(run())
