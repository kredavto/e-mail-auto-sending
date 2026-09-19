from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.modules.contact_storage.service import ContactStorage, contact_data, table_name
from app.modules.contacts.models import Contact, Segment


def test_names_are_readable_safe_unique_and_bounded():
    base = uuid4()
    value = table_name("База автосалонов; DROP TABLE contacts;--", base)
    assert value.startswith("база_автосало")
    assert len(value.encode()) <= 63
    assert ";" not in value and " " not in value
    assert table_name("База", uuid4()) != table_name("База", uuid4())
    assert table_name("😀", base).startswith("contacts__")


def test_sync_retains_unsubscribe_and_original_fields():
    contact = Contact(
        id=uuid4(),
        workspace_id=uuid4(),
        email="test@example.com",
        is_unsubscribed=True,
        custom_fields={"original": "value"},
        updated_at=datetime.now(UTC),
    )
    payload = contact_data(contact)
    assert payload["is_unsubscribed"] is True
    assert payload["custom_fields"]["original"] == "value"
    assert payload["id"] == str(contact.id)


@pytest.mark.asyncio
async def test_snapshot_finishes_only_after_all_batches():
    base = Segment(id=uuid4(), workspace_id=uuid4(), name="Загруженная база")
    contact = Contact(id=uuid4(), workspace_id=base.workspace_id, email="test@example.com")
    db = Mock(scalars=AsyncMock(side_effect=[Mock(all=lambda: [contact]), Mock(all=lambda: [])]))
    storage = ContactStorage(db)
    storage.settings = SimpleNamespace(supabase_contact_storage_url="https://storage.example/sync")
    client = Mock(post=AsyncMock(return_value=Mock(raise_for_status=Mock(), json=lambda: {})))
    assert await storage.sync_base(base, client) == 1
    calls = [call.kwargs["json"] for call in client.post.call_args_list]
    assert [call["action"] for call in calls] == ["begin", "batch", "finish"]
    assert calls[-1]["expected_count"] == 1
    assert len({call["run_id"] for call in calls}) == 1
    assert "contacts.workspace_id" in str(db.scalars.call_args_list[0].args[0])
    assert "contacts.tags" in str(db.scalars.call_args_list[0].args[0])


@pytest.mark.asyncio
async def test_failed_batch_never_finishes_or_deletes_previous_snapshot():
    base = Segment(id=uuid4(), workspace_id=uuid4(), name="База")
    contact = Contact(id=uuid4(), workspace_id=base.workspace_id, email="test@example.com")
    db = Mock(scalars=AsyncMock(return_value=Mock(all=lambda: [contact])))
    storage = ContactStorage(db)
    storage.settings = SimpleNamespace(supabase_contact_storage_url="https://storage.example/sync")
    client = Mock(
        post=AsyncMock(
            side_effect=[
                Mock(raise_for_status=Mock(), json=lambda: {}),
                httpx.ConnectError("offline"),
            ]
        )
    )
    with pytest.raises(httpx.ConnectError):
        await storage.sync_base(base, client)
    assert [c.kwargs["json"]["action"] for c in client.post.call_args_list] == ["begin", "batch"]


@pytest.mark.asyncio
async def test_unconfigured_storage_is_a_noop():
    storage = ContactStorage(Mock())
    storage.settings = SimpleNamespace(
        supabase_contact_storage_url="", supabase_contact_storage_token=SecretStr("")
    )
    assert await storage.sync_all() == {"status": "disabled"}
