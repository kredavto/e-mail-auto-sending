from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.dependencies import TenantContext
from app.core.exceptions import AppError
from app.modules.assistant.router import select_recipients
from app.modules.assistant.schemas import CampaignDraftRequest
from app.modules.assistant.service import AssistantService
from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.contacts.models import Contact
from app.modules.omnichannel.service import StepResult
from app.modules.products.models import Product
from app.modules.scheduler.repository import SchedulerRepository
from app.modules.sequences.models import Sequence, SequenceStep


def draft(**overrides):
    return CampaignDraftRequest(
        **{
            "name": "Schedule",
            "product_name": "Product",
            "template_ids": [uuid4()],
            "contact_ids": [uuid4()],
            "sender_email": "sender@example.com",
            "sender_name": "Team",
            "schedule_start": datetime.now(UTC) + timedelta(days=1),
            "consent_confirmed": True,
            "launch_mode": "scheduled",
            **overrides,
        }
    )


def test_limit_and_aware_schedule():
    assert len(draft(contact_ids=[uuid4() for _ in range(50_000)]).contact_ids) == 50_000
    for changes in [
        {"contact_ids": [uuid4() for _ in range(50_001)]},
        {"contact_ids": []},
        {"schedule_start": "2028-01-01T10:00:00"},
        {"consent_confirmed": False},
    ]:
        with pytest.raises(ValidationError):
            draft(**changes)


@pytest.mark.asyncio
async def test_select_all_is_scoped_and_keeps_unsubscribes_excluded():
    ids = [uuid4() for _ in range(50_000)]
    db = Mock(scalars=AsyncMock(return_value=Mock(all=lambda: ids)))
    tenant = TenantContext(uuid4(), SimpleNamespace(id=uuid4()), "owner")
    result = await select_recipients(search="example", list_id=None, tenant=tenant, db=db)
    assert result["total"] == 50_000
    query = db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "contacts.workspace_id" in str(query)
    assert "contacts.is_unsubscribed IS false" in str(query)
    assert "contacts.has_replied IS false" in str(query)
    assert 50_001 in query.params.values()
    db.scalars.return_value.all = lambda: ids + [uuid4()]
    with pytest.raises(AppError, match="50 000"):
        await select_recipients(search="", list_id=None, tenant=tenant, db=db)


@pytest.mark.asyncio
async def test_scheduler_excludes_future_and_draft_campaigns():
    now = datetime.now(UTC)
    db = Mock(scalars=AsyncMock(return_value=Mock(all=lambda: [])))
    await SchedulerRepository(db).due(now)
    query = db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "campaigns.schedule_start <=" in str(query)
    assert "campaign_contacts.next_send_at <=" in str(query)
    assert ["running", "scheduled"] in query.params.values()
    assert "FOR UPDATE SKIP LOCKED" in str(query)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["draft", "scheduled"])
async def test_creation_schedules_only_when_explicitly_requested(mode, monkeypatch):
    tenant = TenantContext(uuid4(), SimpleNamespace(id=uuid4()), "owner")
    data = draft(launch_mode=mode)
    contact = Contact(
        id=data.contact_ids[0],
        email="lead@example.com",
        is_unsubscribed=False,
        has_replied=False,
        status="new",
    )
    db = Mock(
        flush=AsyncMock(),
        scalars=AsyncMock(
            side_effect=[
                Mock(all=lambda: [contact]),
                Mock(all=lambda: [SimpleNamespace(id=data.template_ids[0])]),
            ]
        ),
    )

    def add(row):
        if not row.id:
            row.id = uuid4()

    db.add.side_effect = add
    svc = AssistantService(db, tenant)
    svc.recipients = AsyncMock(return_value=[])
    svc.validate_campaign = AsyncMock()
    monkeypatch.setattr("app.modules.assistant.service.AuditService.log", AsyncMock())
    campaign = await svc.create_campaign(data)
    assert campaign.status == mode
    assert campaign.schedule_start == data.schedule_start
    assert db.add_all.call_args.args[0][0].next_send_at == data.schedule_start
    assert svc.validate_campaign.await_count == (1 if mode == "scheduled" else 0)


def worker_fixture(monkeypatch, *, deferred=False, next_step=False):
    from app.modules.omnichannel.tasks import orchestrate_step
    from app.modules.sender.exceptions import DeliveryDeferred

    workspace = uuid4()
    campaign = Campaign(
        id=uuid4(),
        workspace_id=workspace,
        sequence_id=uuid4(),
        product_id=uuid4(),
        status="running",
        name="Bulk",
    )
    contact = Contact(id=uuid4(), workspace_id=workspace, email="lead@example.com")
    step = SequenceStep(id=uuid4(), sequence_id=campaign.sequence_id, position=0, step_type="email")
    member = CampaignContact(
        id=uuid4(),
        campaign_id=campaign.id,
        contact_id=contact.id,
        status="queued",
        current_step_index=0,
    )
    sequence = Sequence(
        id=campaign.sequence_id,
        send_window={
            "timezone": "Europe/Moscow",
            "days": ["mon", "tue", "wed", "thu", "fri"],
            "hours": [9, 18],
        },
    )
    product = Product(id=campaign.product_id, workspace_id=workspace)
    mapping = {
        Campaign: campaign,
        Contact: contact,
        SequenceStep: step,
        Product: product,
        Sequence: sequence,
    }
    later = SequenceStep(position=1, delay_days=3, send_hour=10) if next_step else None
    scalar_results = (
        [member, member] if deferred else [member, later, campaign.id, 1 if later else 0]
    )
    db = Mock(
        get=AsyncMock(side_effect=lambda model, _: mapping[model]),
        scalar=AsyncMock(side_effect=scalar_results),
        commit=AsyncMock(),
        flush=AsyncMock(),
        rollback=AsyncMock(),
    )
    context = AsyncMock()
    context.__aenter__.return_value = db
    monkeypatch.setattr("app.database.async_session_factory", Mock(return_value=context))
    execute = AsyncMock(return_value=StepResult("sent", "email", message_id="test"))
    if deferred:
        execute.side_effect = DeliveryDeferred("Hourly limit", 3600)
    monkeypatch.setattr(
        "app.modules.omnichannel.service.OmnichannelOrchestrator",
        Mock(return_value=Mock(execute_step=execute)),
    )
    monkeypatch.setattr("app.core.events.publish_enterprise_event", AsyncMock())
    result = orchestrate_step.run(str(workspace), str(campaign.id), str(contact.id), str(step.id))
    return result, member, campaign, db


def test_rate_limit_is_persisted_for_later_without_advancing(monkeypatch):
    now = datetime.now(UTC)
    result, member, campaign, db = worker_fixture(monkeypatch, deferred=True)
    assert result["status"] == "deferred"
    assert member.status == "active" and member.current_step_index == 0
    assert member.next_send_at >= now + timedelta(seconds=3600)
    assert campaign.status == "running"
    db.rollback.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("later", [False, True])
def test_worker_advances_only_after_delivery(monkeypatch, later):
    result, member, campaign, db = worker_fixture(monkeypatch, next_step=later)
    assert result["status"] == "sent" and member.current_step_index == 1
    assert member.status == ("active" if later else "completed")
    assert campaign.status == ("running" if later else "completed")
    assert (member.next_send_at is not None) == later
    db.commit.assert_awaited_once()
