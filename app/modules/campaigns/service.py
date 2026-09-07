from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.audit import audited
from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.campaigns.repository import CampaignRepository
from app.modules.campaigns.schemas import CampaignCreate, CampaignStats, CampaignUpdate
from app.modules.products.repository import ProductRepository
from app.modules.sequences.service import SequenceService


class CampaignService:
    transitions = {
        "draft": {"scheduled", "running"},
        "scheduled": {"running", "paused"},
        "running": {"paused", "completed"},
        "paused": {"running", "completed"},
        "completed": set(),
    }

    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id, self.repo = (
            db,
            workspace_id,
            CampaignRepository(db, workspace_id),
        )

    @audited("campaign.created", "campaign")
    async def create(self, data: CampaignCreate) -> Campaign:
        sequence_id = data.sequence_id
        if sequence_id is None:
            product = await ProductRepository(self.db, self.workspace_id).get(data.product_id)
            if not product or not product.default_sequence_id:
                raise NotFoundError("У продукта не настроена цепочка по умолчанию")
            sequence_id = product.default_sequence_id
        values = data.model_dump(exclude={"contact_ids", "sequence_id"})
        values["sequence_id"] = sequence_id
        campaign = await self.repo.add(Campaign(workspace_id=self.workspace_id, **values))
        await self.repo.add_contacts(
            [
                CampaignContact(
                    campaign_id=campaign.id, contact_id=item, next_send_at=campaign.schedule_start
                )
                for item in data.contact_ids
            ]
        )
        return campaign

    @audited("campaign.updated", "campaign")
    async def update(self, campaign_id: UUID, data: CampaignUpdate) -> Campaign:
        campaign = await self.repo.get(campaign_id)
        if not campaign:
            raise NotFoundError("Кампания не найдена")
        if campaign.status not in {"draft", "paused"}:
            raise ValueError("Работающую или завершённую кампанию нельзя редактировать")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(campaign, field, value)
        return campaign

    async def transition(self, campaign_id: UUID, target: str) -> Campaign:
        campaign = await self.repo.get(campaign_id)
        if not campaign:
            raise NotFoundError("Кампания не найдена")
        if target not in self.transitions.get(campaign.status, set()):
            raise ValueError(f"Переход {campaign.status} → {target} запрещен")
        if target == "running":
            validation = await SequenceService(self.db, self.workspace_id).validate(
                campaign.sequence_id
            )
            if not validation.valid:
                raise ValueError("Цепочка невалидна: " + "; ".join(validation.errors))
        campaign.status = target
        return campaign

    @staticmethod
    def stats(campaign: Campaign) -> CampaignStats:
        sent = campaign.sent_count or 0
        opened = campaign.opened_count or 0
        clicked = campaign.clicked_count or 0
        replied = campaign.replied_count or 0
        bounced = campaign.bounced_count or 0
        return CampaignStats(
            sent=sent,
            opened=opened,
            clicked=clicked,
            replied=replied,
            bounced=bounced,
            open_rate=round(opened / sent, 4) if sent else 0,
            reply_rate=round(replied / sent, 4) if sent else 0,
        )
