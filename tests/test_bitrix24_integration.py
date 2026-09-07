from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.bitrix24.service import Bitrix24SyncService
from app.modules.contacts.models import Contact
from app.modules.products.models import Product


@pytest.mark.asyncio
async def test_contact_creates_bitrix_lead() -> None:
    workspace_id = uuid4()
    contact = Contact(
        id=uuid4(),
        workspace_id=workspace_id,
        email="lead@example.com",
        first_name="Anna",
        last_name="Ivanova",
        company="Acme",
        position="CEO",
    )
    product = Product(id=uuid4(), workspace_id=workspace_id, name="Premium sites", slug="sites")
    client = Mock(
        find_lead_by_email=AsyncMock(return_value=None), create_lead=AsyncMock(return_value=42)
    )
    db = Mock()
    service = Bitrix24SyncService(db, workspace_id, client)
    assert await service.sync_contact_to_lead(contact, product) == 42
    assert contact.bitrix_lead_id == 42
    client.create_lead.assert_awaited_once()
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_existing_bitrix_lead_is_updated() -> None:
    workspace_id = uuid4()
    contact = Contact(id=uuid4(), workspace_id=workspace_id, email="lead@example.com")
    product = Product(id=uuid4(), workspace_id=workspace_id, name="RKO", slug="rko")
    client = Mock(
        find_lead_by_email=AsyncMock(return_value={"ID": "7"}),
        update_lead=AsyncMock(),
    )
    service = Bitrix24SyncService(Mock(), workspace_id, client)
    assert await service.sync_contact_to_lead(contact, product) == 7
    client.update_lead.assert_awaited_once()


@pytest.mark.asyncio
async def test_outgoing_email_is_logged_as_activity() -> None:
    workspace_id = uuid4()
    contact = Contact(
        id=uuid4(), workspace_id=workspace_id, email="lead@example.com", bitrix_lead_id=77
    )
    client = Mock(create_email_activity=AsyncMock(return_value=88))
    service = Bitrix24SyncService(Mock(), workspace_id, client)
    result = await service.log_email_activity(contact, "Subject", "<p>Body</p>", "message-1")
    assert result == 88
    client.create_email_activity.assert_awaited_once_with(
        owner_id=77,
        owner_type="L",
        subject="Subject",
        description="<p>Body</p>",
        direction="O",
        message_id="message-1",
    )


@pytest.mark.asyncio
async def test_incoming_bitrix_reply_stops_active_sequences() -> None:
    workspace_id = uuid4()
    contact = Contact(
        id=uuid4(),
        workspace_id=workspace_id,
        email="lead@example.com",
        bitrix_lead_id=77,
        has_replied=False,
    )
    client = Mock(
        list_activities=AsyncMock(
            return_value=[{"ID": "99", "OWNER_ID": "77", "OWNER_TYPE_ID": "1"}]
        )
    )
    result = Mock()
    result.all.return_value = [contact]
    db = Mock(scalars=AsyncMock(return_value=result), execute=AsyncMock())
    activities = await Bitrix24SyncService(db, workspace_id, client).check_incoming_replies()
    assert len(activities) == 1
    assert contact.has_replied is True
    assert contact.status == "replied"
    db.execute.assert_awaited_once()
