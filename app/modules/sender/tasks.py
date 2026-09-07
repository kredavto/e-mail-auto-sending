import asyncio
from uuid import UUID

from app.celery_app import celery_app
from app.modules.queue.tasks import DeadLetterTask


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    queue="emails",
)
def send_email_task(self: object, workspace_id: str, payload: dict[str, object]) -> dict[str, str]:
    # Worker creates its own async DB session; API processes never share connections with Celery.
    from app.database import async_session_factory
    from app.modules.sender.schemas import SendEmailRequest
    from app.modules.sender.service import SenderService

    async def run() -> dict[str, str]:
        async with async_session_factory() as db:
            row = await SenderService(db, UUID(workspace_id)).send(
                SendEmailRequest.model_validate(payload)
            )
            await db.commit()
            return {"message_id": str(row.id), "status": row.status}

    return asyncio.run(run())
