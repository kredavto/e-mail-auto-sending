from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.config import Settings
from app.modules.campaigns.models import Campaign
from app.modules.contacts.models import Contact
from app.modules.omnichannel.service import OmnichannelOrchestrator
from app.modules.products.models import Product
from app.modules.sequences.models import SequenceStep
from app.modules.tenchat.models import TenchatProfile
from app.modules.tenchat.service import TenchatService


@pytest.mark.asyncio
async def test_tenchat_outreach_is_persisted() -> None:
    workspace_id = uuid4()
    profile = TenchatProfile(
        id=uuid4(), workspace_id=workspace_id, tenchat_user_id="tc-1", username="anna"
    )
    client = Mock(send_message=AsyncMock(return_value={"id": "msg-1", "conversation_id": "c-1"}))
    db = Mock()
    service = TenchatService(db, workspace_id, client=client, settings=Settings(_env_file=None))
    service._check_daily_limit = AsyncMock()  # type: ignore[method-assign]
    message = await service.send_outreach(profile, "Здравствуйте")
    assert message.external_message_id == "msg-1"
    assert message.direction == "O"
    db.add.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_reply_in_any_channel_skips_step() -> None:
    workspace_id = uuid4()
    contact = Contact(
        id=uuid4(), workspace_id=workspace_id, email="lead@example.com", has_replied=True
    )
    step = SequenceStep(id=uuid4(), sequence_id=uuid4(), position=0, step_type="email")
    product = Product(id=uuid4(), workspace_id=workspace_id, name="Sites", slug="sites")
    campaign = Campaign(
        id=uuid4(),
        workspace_id=workspace_id,
        product_id=product.id,
        sequence_id=step.sequence_id,
        sender_email="sender@example.com",
        sender_name="Sender",
    )
    db = Mock()
    orchestrator = OmnichannelOrchestrator(db, workspace_id)
    orchestrator.tenchat.has_replies = AsyncMock(return_value=False)
    result = await orchestrator.execute_step(contact, step, product, campaign)
    assert result.status == "skipped"
    assert result.reason == "already_replied"
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_tenchat_reply_stops_active_sequences() -> None:
    workspace_id, contact_id = uuid4(), uuid4()
    profile = TenchatProfile(
        id=uuid4(),
        workspace_id=workspace_id,
        contact_id=contact_id,
        tenchat_user_id="tc-1",
    )
    contact = Contact(
        id=contact_id, workspace_id=workspace_id, email="lead@example.com", has_replied=False
    )
    client = Mock(
        get_conversations=AsyncMock(
            return_value={"items": [{"id": "conversation-1", "user_id": "tc-1"}]}
        ),
        get_messages=AsyncMock(
            return_value={
                "items": [{"id": "incoming-1", "direction": "incoming", "text": "Интересно"}]
            }
        ),
    )
    db = Mock()
    db.scalar = AsyncMock(side_effect=[profile, None])
    db.get = AsyncMock(return_value=contact)
    db.execute = AsyncMock()
    assert await TenchatService(db, workspace_id, client=client).check_replies() == 1
    assert contact.has_replied is True
    assert contact.status == "replied"
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_tenchat_profile_falls_back_to_email() -> None:
    from app.modules.omnichannel.service import StepResult

    workspace_id = uuid4()
    contact = Contact(id=uuid4(), workspace_id=workspace_id, email="lead@example.com")
    step = SequenceStep(id=uuid4(), sequence_id=uuid4(), position=0, step_type="tenchat_message")
    product = Product(id=uuid4(), workspace_id=workspace_id, name="Sites", slug="sites")
    campaign = Campaign(
        id=uuid4(),
        workspace_id=workspace_id,
        product_id=product.id,
        sequence_id=step.sequence_id,
        sender_email="sender@example.com",
        sender_name="Sender",
    )
    db = Mock()
    orchestrator = OmnichannelOrchestrator(db, workspace_id)
    orchestrator.tenchat.has_replies = AsyncMock(return_value=False)
    orchestrator.tenchat.get_profile_for_contact = AsyncMock(return_value=None)
    orchestrator._send_email = AsyncMock(  # type: ignore[method-assign]
        return_value=StepResult("sent", "email", "no_tenchat_profile", "email-1")
    )
    result = await orchestrator.execute_step(contact, step, product, campaign)
    assert result.channel == "email"
    assert result.reason == "no_tenchat_profile"
