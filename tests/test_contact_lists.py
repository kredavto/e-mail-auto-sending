from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.exceptions import NotFoundError
from app.modules.contacts.lists import ContactLists, list_tag
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.router import bulk
from app.modules.contacts.schemas import BulkContactsCreate, BulkResult, ContactListCreate


async def test_list_lookup_is_tenant_scoped_and_missing_list_is_rejected():
    workspace_id, list_id = uuid4(), uuid4()
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await ContactLists(db, workspace_id).get(list_id)
    query = db.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert workspace_id in query.params.values() and list_id in query.params.values()
    assert "contact_list" in query.params.values()


async def test_membership_update_is_idempotent_and_preserves_other_tags():
    workspace_id, list_id = uuid4(), uuid4()
    db = SimpleNamespace(execute=AsyncMock())
    await ContactLists(db, workspace_id).attach(list_id, ["a@example.com"])
    query = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(query)
    assert "NOT" in sql and "@>" in sql and "||" in sql
    assert workspace_id in query.params.values()
    assert [list_tag(list_id)] in query.params.values()
    assert ["a@example.com"] in query.params.values()


async def test_list_filter_applies_to_both_rows_and_total():
    workspace_id, list_id = uuid4(), uuid4()
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=0), scalars=AsyncMock(return_value=Mock(all=lambda: []))
    )
    assert await ContactRepository(db, workspace_id).list_all(0, 25, list_id) == ([], 0)
    for statement in (db.scalar.call_args.args[0], db.scalars.call_args.args[0]):
        query = statement.compile(dialect=postgresql.dialect())
        assert workspace_id in query.params.values()
        assert [list_tag(list_id)] in query.params.values()


async def test_duplicate_contact_still_joins_named_list():
    list_id = uuid4()
    tenant = SimpleNamespace(workspace_id=uuid4(), user=SimpleNamespace(id=uuid4()))
    with (
        patch("app.modules.contacts.router.ContactLists") as lists,
        patch("app.modules.contacts.router.ContactService") as service,
        patch("app.modules.contacts.router.BillingService") as billing,
    ):
        lists.return_value.get = AsyncMock()
        lists.return_value.attach = AsyncMock()
        service.return_value.bulk = AsyncMock(
            return_value=BulkResult(created=0, skipped=1, errors=[])
        )
        billing.return_value.check_limits = AsyncMock()
        await bulk(
            BulkContactsCreate(list_id=list_id, contacts=[{"email": "a@example.com"}]),
            tenant,
            Mock(),
        )
        lists.return_value.get.assert_awaited_once_with(list_id)
        lists.return_value.attach.assert_awaited_once_with(list_id, ["a@example.com"])


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_list_name_validation(name):
    with pytest.raises(ValidationError):
        ContactListCreate(name=name)
