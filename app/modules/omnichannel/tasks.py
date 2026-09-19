import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select

from app.celery_app import celery_app
from app.modules.queue.tasks import DeadLetterTask
from app.modules.sender.exceptions import DeliveryDeferred


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
    from app.modules.campaigns.models import Campaign, CampaignContact
    from app.modules.contacts.models import Contact
    from app.modules.omnichannel.service import OmnichannelOrchestrator
    from app.modules.products.models import Product
    from app.modules.scheduler.service import SchedulerService
    from app.modules.sequences.models import Sequence, SequenceStep

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
                or contact.workspace_id != campaign.workspace_id
                or step.sequence_id != campaign.sequence_id
            ):
                raise ValueError("Omnichannel entities not found")
            product = await db.get(Product, campaign.product_id)
            if not product:
                raise ValueError("Product not found")
            membership_query = (
                select(CampaignContact)
                .where(
                    CampaignContact.campaign_id == campaign.id,
                    CampaignContact.contact_id == contact.id,
                )
                .with_for_update()
            )
            membership = await db.scalar(membership_query)
            if (
                not membership
                or membership.status != "queued"
                or membership.current_step_index != step.position
            ):
                return {"status": "skipped", "reason": "step_not_pending"}
            if campaign.status not in {"running", "scheduled"}:
                membership.status = "active"
                membership.next_send_at = datetime.now(UTC)
                await db.commit()
                return {"status": "paused", "reason": "campaign_not_running"}
            try:
                result = await OmnichannelOrchestrator(db, UUID(workspace_id)).execute_step(
                    contact, step, product, campaign
                )
            except DeliveryDeferred as exc:
                # Roll back counters/events and persist a future retry in PostgreSQL.
                await db.rollback()
                membership = await db.scalar(membership_query)
                if membership and membership.status == "queued":
                    membership.status = "active"
                    membership.next_send_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after)
                await db.commit()
                return {"status": "deferred", "reason": str(exc)}
            membership.current_step_index += 1
            next_step = await db.scalar(
                select(SequenceStep).where(
                    SequenceStep.sequence_id == campaign.sequence_id,
                    SequenceStep.position == membership.current_step_index,
                )
            )
            sequence = await db.get(Sequence, campaign.sequence_id)
            if next_step and sequence and result.status != "skipped":
                membership.status = "active"
                membership.next_send_at = SchedulerService.next_send_time(
                    datetime.now(UTC),
                    next_step.delay_days,
                    sequence.send_window,
                    next_step.send_hour,
                )
            else:
                membership.status = "completed"
                membership.next_send_at = None
            await db.flush()
            await db.scalar(select(Campaign.id).where(Campaign.id == campaign.id).with_for_update())
            pending = await db.scalar(
                select(func.count())
                .select_from(CampaignContact)
                .where(
                    CampaignContact.campaign_id == campaign.id,
                    CampaignContact.status.in_(["active", "queued"]),
                )
            )
            if not pending and campaign.status == "running":
                from app.core.events import IntegrationEvent, publish_enterprise_event

                campaign.status = "completed"
                await publish_enterprise_event(
                    db,
                    IntegrationEvent(
                        workspace_id=campaign.workspace_id,
                        resource_type="campaign",
                        resource_id=campaign.id,
                        data={"name": campaign.name},
                        kind="campaign.completed",
                    ),
                )
            await db.commit()
            return {
                "status": result.status,
                "channel": result.channel,
                "reason": result.reason,
                "message_id": result.message_id,
            }

    return asyncio.run(run())
