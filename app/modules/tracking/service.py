from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import IntegrationEvent, publish_enterprise_event
from app.core.exceptions import NotFoundError
from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.contacts.models import Contact
from app.modules.sender.models import EmailMessage
from app.modules.tracking.models import TrackingEvent
from app.modules.tracking.repository import TrackingRepository


class TrackingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db, self.repo = db, TrackingRepository(db)

    async def record(
        self, message_id: UUID, event_type: str, metadata: dict[str, object] | None = None
    ) -> None:
        message = await self.db.get(EmailMessage, message_id)
        if not message:
            return
        now = datetime.now(UTC)
        await self.repo.add(
            TrackingEvent(
                message_id=message_id,
                event_type=event_type,
                occurred_at=now,
                metadata_json=metadata or {},
            )
        )
        campaign = await self.db.get(Campaign, message.campaign_id) if message.campaign_id else None
        contact = await self.db.get(Contact, message.contact_id) if message.contact_id else None
        if event_type == "open" and message.opened_at is None:
            message.opened_at = now
            if campaign:
                campaign.opened_count += 1
            if contact:
                contact.status = "opened"
        elif event_type == "click" and message.clicked_at is None:
            message.clicked_at = now
            if campaign:
                campaign.clicked_count += 1
            if contact:
                contact.status = "clicked"
        elif event_type in {"bounce", "complaint"}:
            message.status = event_type
            if campaign and event_type == "bounce":
                campaign.bounced_count += 1
            if contact:
                contact.status = event_type
        public_event = {
            "open": "email.opened",
            "click": "email.clicked",
            "bounce": "email.bounced",
            "complaint": "email.complained",
        }.get(event_type)
        if public_event:
            await publish_enterprise_event(
                self.db,
                IntegrationEvent(
                    workspace_id=message.workspace_id,
                    resource_type="email",
                    resource_id=message.id,
                    data={
                        "campaign_id": str(message.campaign_id) if message.campaign_id else None,
                        "contact_id": str(message.contact_id) if message.contact_id else None,
                        **(metadata or {}),
                    },
                    kind=public_event,
                ),
            )

    async def unsubscribe(self, message_id: UUID) -> bool:
        message = await self.db.get(EmailMessage, message_id)
        if not message or not message.contact_id:
            return False
        contact = await self.db.get(Contact, message.contact_id)
        if not contact:
            return False
        contact.is_unsubscribed = True
        contact.status = "unsubscribed"
        return True

    async def record_meeting(
        self, workspace_id: UUID, contact_id: UUID, campaign_id: UUID | None = None
    ) -> None:
        contact = await self.db.scalar(
            select(Contact).where(Contact.id == contact_id, Contact.workspace_id == workspace_id)
        )
        if not contact:
            raise NotFoundError("Контакт не найден")
        campaign = None
        if campaign_id:
            campaign = await self.db.scalar(
                select(Campaign).where(
                    Campaign.id == campaign_id, Campaign.workspace_id == workspace_id
                )
            )
            if not campaign:
                raise NotFoundError("Кампания не найдена")
        else:
            linked_campaign_id = await self.db.scalar(
                select(CampaignContact.campaign_id)
                .join(Campaign, Campaign.id == CampaignContact.campaign_id)
                .where(
                    CampaignContact.contact_id == contact_id,
                    Campaign.workspace_id == workspace_id,
                )
                .order_by(Campaign.created_at.desc())
                .limit(1)
            )
            if linked_campaign_id:
                campaign = await self.db.get(Campaign, linked_campaign_id)
        if contact.status != "meeting_booked" and campaign:
            campaign.meeting_count += 1
        contact.status = "meeting_booked"
        await publish_enterprise_event(
            self.db,
            IntegrationEvent(
                workspace_id=workspace_id,
                resource_type="contact",
                resource_id=contact.id,
                data={"campaign_id": str(campaign.id) if campaign else None},
                kind="meeting.booked",
            ),
        )
