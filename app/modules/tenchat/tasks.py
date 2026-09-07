import asyncio
from uuid import UUID

from sqlalchemy import select

from app.celery_app import celery_app
from app.modules.queue.tasks import DeadLetterTask


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.tenchat.tasks.sync_tenchat_profiles",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    queue="enrichment",
)
def sync_tenchat_profiles(self: object, workspace_id: str, user_ids: list[str]) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.tenchat.service import TenchatService

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            synced = await TenchatService(db, UUID(workspace_id)).sync_profiles(user_ids)
            await db.commit()
            return {"synced": synced}

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.tenchat.tasks.send_tenchat_outreach",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    queue="enrichment",
)
def send_tenchat_outreach(
    self: object, workspace_id: str, profile_id: str, text: str
) -> dict[str, str]:
    from app.database import async_session_factory
    from app.modules.tenchat.models import TenchatProfile
    from app.modules.tenchat.service import TenchatService

    async def run() -> dict[str, str]:
        async with async_session_factory() as db:
            profile = await db.get(TenchatProfile, UUID(profile_id))
            if not profile or str(profile.workspace_id) != workspace_id:
                raise ValueError("Tenchat profile not found")
            message = await TenchatService(db, UUID(workspace_id)).send_outreach(profile, text)
            await db.commit()
            return {"message_id": str(message.id), "status": message.status}

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.tenchat.tasks.send_tenchat_sequence",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    queue="enrichment",
)
def send_tenchat_sequence(
    self: object, workspace_id: str, profile_id: str, texts: list[str]
) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.tenchat.models import TenchatProfile
    from app.modules.tenchat.service import TenchatService

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            profile = await db.get(TenchatProfile, UUID(profile_id))
            if not profile or str(profile.workspace_id) != workspace_id:
                raise ValueError("Tenchat profile not found")
            service = TenchatService(db, UUID(workspace_id))
            for text in texts:
                await service.send_outreach(profile, text)
            await db.commit()
            return {"sent": len(texts)}

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.tenchat.tasks.check_incoming_replies",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    queue="enrichment",
)
def check_incoming_replies(self: object, workspace_id: str | None = None) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.tenchat.service import TenchatService
    from app.modules.users.models import Workspace

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            workspace_ids = (
                [UUID(workspace_id)]
                if workspace_id
                else list((await db.scalars(select(Workspace.id))).all())
            )
            replies = 0
            for value in workspace_ids:
                replies += await TenchatService(db, value).check_replies()
            await db.commit()
            return {"replies": replies}

    return asyncio.run(run())
