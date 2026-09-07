from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from celery import Celery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import IntegrationEvent, publish_enterprise_event
from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.contacts.models import Contact
from app.modules.scheduler.repository import SchedulerRepository
from app.modules.sequences.models import Sequence, SequenceStep

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class SchedulerService:
    def __init__(self, db: AsyncSession | None = None, queue: Celery | None = None) -> None:
        self.db = db
        self.queue = queue

    @staticmethod
    def next_send_time(
        after: datetime,
        delay_days: int,
        window: dict[str, object],
        preferred_hour: int | None = None,
    ) -> datetime:
        timezone_name = str(window.get("timezone", "Europe/Moscow"))
        tz = ZoneInfo("Europe/Moscow" if timezone_name == "MSK" else timezone_name)
        local = after.astimezone(tz) + timedelta(days=delay_days)
        days_value = window.get("days")
        days = (
            set(days_value) if isinstance(days_value, list) else {"mon", "tue", "wed", "thu", "fri"}
        )
        hours_value = window.get("hours")
        hours = hours_value if isinstance(hours_value, list) and len(hours_value) == 2 else [9, 18]
        start, end = int(str(hours[0])), int(str(hours[1]))
        hour = preferred_hour if preferred_hour is not None else start
        local = local.replace(
            hour=max(start, min(hour, end - 1)), minute=0, second=0, microsecond=0
        )
        if delay_days == 0 and local < after.astimezone(tz):
            local += timedelta(days=1)
        while DAY_NAMES[local.weekday()] not in days:
            local += timedelta(days=1)
        return local.astimezone(UTC)

    @staticmethod
    def should_stop(contact: Contact, conditions: dict[str, bool]) -> bool:
        return bool(
            (conditions.get("replied") and contact.has_replied)
            or (conditions.get("unsubscribed") and contact.is_unsubscribed)
            or (conditions.get("bounced") and contact.status == "bounced")
            or (conditions.get("meeting_booked") and contact.status == "meeting_booked")
        )

    async def dispatch_due(self, now: datetime, limit: int = 1000) -> int:
        if self.db is None or self.queue is None:
            raise RuntimeError("SchedulerService requires database and queue")
        rows = await SchedulerRepository(self.db).due(now, limit)
        dispatched = 0
        touched_campaigns: dict[object, Campaign] = {}
        for row in rows:
            campaign = await self.db.get(Campaign, row.campaign_id)
            contact = await self.db.get(Contact, row.contact_id)
            if not campaign or not contact:
                row.status = "invalid"
                continue
            touched_campaigns[campaign.id] = campaign
            sequence = await self.db.get(Sequence, campaign.sequence_id)
            if not sequence or self.should_stop(contact, sequence.stop_conditions):
                row.status = "stopped"
                continue
            steps = list(
                (
                    await self.db.scalars(
                        select(SequenceStep)
                        .where(SequenceStep.sequence_id == sequence.id)
                        .order_by(SequenceStep.position)
                    )
                ).all()
            )
            if row.current_step_index >= len(steps):
                row.status = "completed"
                row.next_send_at = None
                continue
            step = steps[row.current_step_index]
            self.queue.send_task(
                "app.modules.omnichannel.tasks.orchestrate_step",
                args=[str(campaign.workspace_id), str(campaign.id), str(contact.id), str(step.id)],
                queue="emails",
                priority=9,
            )
            row.current_step_index += 1
            if row.current_step_index >= len(steps):
                row.status = "completed"
                row.next_send_at = None
            else:
                next_step = steps[row.current_step_index]
                row.next_send_at = self.next_send_time(
                    now, next_step.delay_days, sequence.send_window, next_step.send_hour
                )
            dispatched += 1
        if isinstance(self.db, AsyncSession):
            for campaign in touched_campaigns.values():
                active = await self.db.scalar(
                    select(func.count())
                    .select_from(CampaignContact)
                    .where(
                        CampaignContact.campaign_id == campaign.id,
                        CampaignContact.status == "active",
                    )
                )
                if not active and campaign.status == "running":
                    campaign.status = "completed"
                    await publish_enterprise_event(
                        self.db,
                        IntegrationEvent(
                            workspace_id=campaign.workspace_id,
                            resource_type="campaign",
                            resource_id=campaign.id,
                            data={"name": campaign.name},
                            kind="campaign.completed",
                        ),
                    )
        return dispatched
