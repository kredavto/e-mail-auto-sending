import asyncio
from uuid import UUID

from sqlalchemy import select

from app.celery_app import celery_app
from app.modules.queue.tasks import DeadLetterTask


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.bitrix24.tasks.sync_contacts_batch",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    queue="bitrix",
)
def sync_contacts_batch(
    self: object,
    workspace_id: str,
    product_id: str,
    contact_ids: list[str],
    campaign_id: str | None = None,
) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.bitrix24.service import Bitrix24SyncService
    from app.modules.contacts.models import Contact
    from app.modules.products.models import Product

    async def run() -> dict[str, int]:
        workspace_uuid, product_uuid = UUID(workspace_id), UUID(product_id)
        async with async_session_factory() as db:
            product = await db.get(Product, product_uuid)
            if not product or product.workspace_id != workspace_uuid:
                raise ValueError("Product not found")
            query = select(Contact).where(Contact.workspace_id == workspace_uuid)
            if contact_ids:
                query = query.where(Contact.id.in_([UUID(value) for value in contact_ids]))
            contacts = list((await db.scalars(query)).all())
            service = Bitrix24SyncService(db, workspace_uuid)
            synced = 0
            for contact in contacts:
                await service.sync_contact_to_lead(
                    contact, product, UUID(campaign_id) if campaign_id else None
                )
                synced += 1
            await db.commit()
            return {"synced": synced}

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.bitrix24.tasks.create_bitrix_activity",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    queue="bitrix",
)
def create_bitrix_activity(
    self: object, workspace_id: str, contact_id: str, subject: str, html_body: str, message_id: str
) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.bitrix24.service import Bitrix24SyncService
    from app.modules.contacts.models import Contact

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            contact = await db.get(Contact, UUID(contact_id))
            if not contact or str(contact.workspace_id) != workspace_id:
                raise ValueError("Contact not found")
            activity_id = await Bitrix24SyncService(db, UUID(workspace_id)).log_email_activity(
                contact, subject, html_body, message_id
            )
            await db.commit()
            return {"activity_id": activity_id}

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.bitrix24.tasks.check_incoming_replies",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    queue="bitrix",
)
def check_incoming_replies(self: object) -> dict[str, int]:
    from app.database import async_session_factory
    from app.modules.bitrix24.service import Bitrix24SyncService
    from app.modules.users.models import Workspace

    async def run() -> dict[str, int]:
        async with async_session_factory() as db:
            workspaces = list((await db.scalars(select(Workspace.id))).all())
            count = 0
            statuses = 0
            for workspace_id in workspaces:
                service = Bitrix24SyncService(db, workspace_id)
                count += len(await service.check_incoming_replies())
                statuses += await service.sync_statuses()
            await db.commit()
            return {"activities": count, "statuses_updated": statuses}

    return asyncio.run(run())
