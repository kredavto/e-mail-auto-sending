import asyncio

from app.celery_app import celery_app
from app.modules.queue.tasks import DeadLetterTask


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.hunter.tasks.verify_emails_batch",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    queue="enrichment",
)
def verify_emails_batch(self: object, emails: list[str]) -> list[dict[str, object]]:
    from app.modules.hunter.service import HunterService

    async def run() -> list[dict[str, object]]:
        service = HunterService()
        return [await service.verify(email) for email in emails]

    return asyncio.run(run())
