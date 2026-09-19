import asyncio
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.celery_app import celery_app


@celery_app.task(
    name="app.modules.contact_storage.tasks.sync_contacts",
    queue="enrichment",
    autoretry_for=(httpx.HTTPError, DBAPIError),
    retry_backoff=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def sync_contacts(workspace_id: str | None = None, base_id: str | None = None) -> dict:
    import app.models  # noqa: F401 — register foreign-key targets in standalone workers
    from app.database import async_session_factory
    from app.modules.contact_storage.service import ContactStorage

    workspace = UUID(workspace_id) if workspace_id else None
    base = UUID(base_id) if base_id else None
    if (workspace is None) != (base is None):
        raise ValueError("Workspace and base must be specified together")

    async def run():
        async with async_session_factory() as db:
            # Serialize repeated upload completion events for the same base.
            await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"contact-storage:{workspace}:{base}"},
            )
            result = await ContactStorage(db).sync_all(workspace, base)
            await db.commit()
            return result

    return asyncio.run(run())
