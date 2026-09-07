import asyncio

from app.celery_app import celery_app
from app.modules.queue.tasks import DeadLetterTask


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.ses.tasks.process_ses_notification",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    queue="tracking",
)
def process_ses_notification(self: object, payload: dict[str, object]) -> dict[str, str]:
    from app.database import async_session_factory
    from app.modules.ses.service import SESWebhookHandler

    async def run() -> dict[str, str]:
        async with async_session_factory() as db:
            event = await SESWebhookHandler(db).handle(payload)
            await db.commit()
            return {"status": "ok", "event": event}

    return asyncio.run(run())
