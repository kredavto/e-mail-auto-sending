from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True)
class CampaignStartedEvent(DomainEvent):
    campaign_id: str = ""
