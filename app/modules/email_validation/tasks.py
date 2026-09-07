import asyncio
from uuid import UUID

from app.celery_app import celery_app


@celery_app.task(name="app.modules.email_validation.tasks.validate_batch")  # type: ignore[untyped-decorator]
def validate_batch(workspace_id: str, emails: list[str]) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.email_validation.service import EmailValidationService

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            service = EmailValidationService(db, UUID(workspace_id))
            rows = [await service.validate(email) for email in emails]
            await db.commit()
            return {"validated": len(rows)}

    return asyncio.run(run())
