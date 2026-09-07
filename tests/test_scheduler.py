from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.contacts.models import Contact
from app.modules.scheduler.service import SchedulerService
from app.modules.sequences.models import Sequence, SequenceStep
from app.modules.templates.models import Template

WINDOW = {
    "days": ["mon", "tue", "wed", "thu", "fri"],
    "hours": [9, 18],
    "timezone": "Europe/Moscow",
}


def test_weekend_moves_to_monday() -> None:
    friday = datetime(2026, 9, 4, 16, tzinfo=UTC)
    result = SchedulerService.next_send_time(friday, delay_days=1, window=WINDOW)
    assert result.astimezone().weekday() == 0


def test_replied_contact_stops_sequence() -> None:
    contact = Contact(workspace_id=uuid4(), email="lead@example.com", has_replied=True)
    assert SchedulerService.should_stop(contact, {"replied": True})
    assert not SchedulerService.should_stop(contact, {"replied": False})


@pytest.mark.asyncio
async def test_dispatch_due_enqueues_and_advances() -> None:
    now = datetime(2026, 9, 7, 7, tzinfo=UTC)
    workspace_id, campaign_id, contact_id, sequence_id, template_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    row = CampaignContact(
        campaign_id=campaign_id,
        contact_id=contact_id,
        current_step_index=0,
        next_send_at=now,
        status="active",
    )
    campaign = Campaign(
        id=campaign_id,
        workspace_id=workspace_id,
        product_id=uuid4(),
        sequence_id=sequence_id,
        sender_email="sender@example.com",
        sender_name="Sender",
        schedule_start=now,
        status="running",
    )
    contact = Contact(
        id=contact_id,
        workspace_id=workspace_id,
        email="lead@example.com",
        first_name="Анна",
        company="Альфа",
        position="CEO",
        has_replied=False,
        is_unsubscribed=False,
        status="new",
    )
    sequence = Sequence(
        id=sequence_id,
        workspace_id=workspace_id,
        product_id=campaign.product_id,
        name="Five emails",
        stop_conditions={"replied": True},
        send_window=WINDOW,
    )
    step = SequenceStep(
        sequence_id=sequence_id,
        position=0,
        step_type="email",
        template_id=template_id,
        delay_days=0,
    )
    template = Template(
        id=template_id,
        workspace_id=workspace_id,
        name="First",
        category="first_contact",
        subject_template="Здравствуйте, {{first_name}}",
        editor_state={},
        html_body="<p>{{company}}</p>",
        text_body="{{company}}",
    )
    result_due, result_steps = Mock(), Mock()
    result_due.all.return_value = [row]
    result_steps.all.return_value = [step]
    db = Mock()
    db.scalars = AsyncMock(side_effect=[result_due, result_steps])

    async def get(model: object, item_id: object) -> object | None:
        return {
            (Campaign, campaign_id): campaign,
            (Contact, contact_id): contact,
            (Sequence, sequence_id): sequence,
            (Template, template_id): template,
        }.get((model, item_id))

    db.get = AsyncMock(side_effect=get)
    queue = Mock()
    dispatched = await SchedulerService(db, queue).dispatch_due(now)
    assert dispatched == 1
    assert row.status == "completed"
    queue.send_task.assert_called_once()
    assert queue.send_task.call_args.kwargs["queue"] == "emails"


@pytest.mark.asyncio
async def test_dispatch_stops_replied_contact() -> None:
    now = datetime.now(UTC)
    row = CampaignContact(campaign_id=uuid4(), contact_id=uuid4(), status="active")
    campaign = Campaign(
        id=row.campaign_id,
        workspace_id=uuid4(),
        product_id=uuid4(),
        sequence_id=uuid4(),
        sender_email="sender@example.com",
        sender_name="Sender",
        schedule_start=now,
        status="running",
    )
    contact = Contact(
        id=row.contact_id,
        workspace_id=campaign.workspace_id,
        email="lead@example.com",
        has_replied=True,
    )
    sequence = Sequence(
        id=campaign.sequence_id,
        workspace_id=campaign.workspace_id,
        product_id=campaign.product_id,
        name="Sequence",
        stop_conditions={"replied": True},
        send_window=WINDOW,
    )
    due_result = Mock()
    due_result.all.return_value = [row]
    db = Mock(scalars=AsyncMock(return_value=due_result))
    db.get = AsyncMock(side_effect=[campaign, contact, sequence])
    queue = Mock()
    assert await SchedulerService(db, queue).dispatch_due(now) == 0
    assert row.status == "stopped"
    queue.send_task.assert_not_called()
