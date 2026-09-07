import asyncio
from uuid import UUID

from app.celery_app import celery_app
from app.modules.queue.tasks import DeadLetterTask


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.linkedin.tasks.process_linkedin_export",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    queue="enrichment",
)
def process_linkedin_export(
    self: object, workspace_id: str, export_id: str, csv_content: str
) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.linkedin.models import LinkedInExport
    from app.modules.linkedin.service import LinkedInService

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            export = await db.get(LinkedInExport, UUID(export_id))
            if not export or str(export.workspace_id) != workspace_id:
                raise ValueError("LinkedIn export not found")
            imported = await LinkedInService(db, UUID(workspace_id)).process_export(
                export, csv_content
            )
            await db.commit()
            return {"imported": imported}

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.linkedin.tasks.enrich_linkedin_emails",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    queue="enrichment",
)
def enrich_linkedin_emails(
    self: object, workspace_id: str, profile_ids: list[str]
) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.linkedin.service import LinkedInService

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            result = await LinkedInService(db, UUID(workspace_id)).enrich_emails(
                [UUID(value) for value in profile_ids] or None
            )
            await db.commit()
            return result

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.linkedin.tasks.sync_linkedin_lead_gen_forms",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    queue="enrichment",
)
def sync_linkedin_lead_gen_forms(
    self: object, workspace_id: str, ad_account_id: str
) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.linkedin.service import LinkedInService

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            result = await LinkedInService(db, UUID(workspace_id)).sync_lead_gen_forms(
                ad_account_id
            )
            await db.commit()
            return result

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.linkedin.tasks.create_linkedin_matched_audience",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    queue="enrichment",
)
def create_linkedin_matched_audience(self: object, name: str, emails: list[str]) -> dict[str, str]:
    from app.modules.linkedin.client import LinkedInClient

    async def run() -> dict[str, str]:
        return {"audience_id": await LinkedInClient().create_matched_audience(name, emails)}

    return asyncio.run(run())
