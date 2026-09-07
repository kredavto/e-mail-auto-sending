from datetime import UTC, datetime
from uuid import uuid4

from app.modules.campaigns.models import Campaign
from app.modules.campaigns.service import CampaignService


def test_campaign_stats_avoid_division_by_zero() -> None:
    campaign = Campaign(
        workspace_id=uuid4(),
        product_id=uuid4(),
        name="Test",
        sequence_id=uuid4(),
        sender_email="sender@example.com",
        sender_name="Sender",
        schedule_start=datetime.now(UTC),
    )
    stats = CampaignService.stats(campaign)
    assert stats.open_rate == 0
    assert stats.reply_rate == 0
