import asyncio
from uuid import UUID

from app.celery_app import celery_app


@celery_app.task(name="app.modules.enrichment.tasks.enrich_batch")  # type: ignore[untyped-decorator]
def enrich_batch(workspace_id: str, contact_ids: list[str]) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.enrichment.service import EnrichmentOrchestrator

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            service = EnrichmentOrchestrator(db, UUID(workspace_id))
            rows = [await service.enrich(UUID(contact_id)) for contact_id in contact_ids]
            await db.commit()
            return {"enriched": sum(row.email is not None for row in rows), "total": len(rows)}

    return asyncio.run(run())
