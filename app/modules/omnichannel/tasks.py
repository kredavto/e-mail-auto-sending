import asyncio
from uuid import UUID

from app.celery_app import celery_app
from app.modules.queue.tasks import DeadLetterTask


@celery_app.task(  # type: ignore[untyped-decorator]
    base=DeadLetterTask,
    name="app.modules.omnichannel.tasks.orchestrate_step",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    queue="emails",
)
def orchestrate_step(
    self: object, workspace_id: str, campaign_id: str, contact_id: str, step_id: str
) -> dict[str, str | None]:
    from app.database import async_session_factory
    from app.modules.campaigns.models import Campaign
    from app.modules.contacts.models import Contact
    from app.modules.omnichannel.service import OmnichannelOrchestrator
    from app.modules.products.models import Product
    from app.modules.sequences.models import SequenceStep

    async def run() -> dict[str, str | None]:
        async with async_session_factory() as db:
            campaign = await db.get(Campaign, UUID(campaign_id))
            contact = await db.get(Contact, UUID(contact_id))
            step = await db.get(SequenceStep, UUID(step_id))
            if (
                not campaign
                or not contact
                or not step
                or str(campaign.workspace_id) != workspace_id
            ):
                raise ValueError("Omnichannel entities not found")
            product = await db.get(Product, campaign.product_id)
            if not product:
                raise ValueError("Product not found")
            result = await OmnichannelOrchestrator(db, UUID(workspace_id)).execute_step(
                contact, step, product, campaign
            )
            await db.commit()
            return {
                "status": result.status,
                "channel": result.channel,
                "reason": result.reason,
                "message_id": result.message_id,
            }

    return asyncio.run(run())
