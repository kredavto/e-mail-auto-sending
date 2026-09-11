import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import UploadFile
from openpyxl import Workbook
from pydantic import ValidationError

from app.core.exceptions import AppError
from app.modules.contacts.importing import prepare_import_rows
from app.modules.contacts.router import import_contacts
from app.modules.contacts.schemas import BulkContactsCreate, BulkResult
from app.modules.file_upload.service import FileService


@pytest.mark.parametrize("separator", [",", ";", " ", "\n", "\r\n", "\t", "\u00a0"])
def test_multi_email_preserves_row_data(separator):
    contacts, errors = prepare_import_rows(
        [
            {
                "email": f"INFO@example.com{separator}sales@example.com",
                "full_name": "Иванов Иван",
                "company": "Компания",
                "custom_fields": {"city": "Москва"},
            }
        ]
    )
    assert [str(c.email) for c in contacts] == ["info@example.com", "sales@example.com"]
    assert not errors
    assert all(
        c.full_name == "Иванов Иван"
        and c.company == "Компания"
        and c.custom_fields == {"city": "Москва"}
        for c in contacts
    )


def test_good_addresses_survive_invalid_sibling_and_empty_rows():
    contacts, errors = prepare_import_rows(
        [{}, {"email": "a@example.com;bad;b@example.com"}, {"email": "", "company": "Компания"}]
    )
    assert [str(c.email) for c in contacts] == ["a@example.com", "b@example.com"]
    assert len(errors) == 2 and "Строка 3" in errors[0] and "Строка 4" in errors[1]


def test_limit_applies_after_splitting():
    emails = ";".join(f"c{i}@example.com" for i in range(10000))
    contacts, errors = prepare_import_rows([{"email": emails}])
    assert len(contacts) == 10000 and not errors
    with pytest.raises(AppError, match="10000"):
        prepare_import_rows([{"email": f"{emails};extra@example.com"}])


def test_bulk_contact_schema_accepts_10000_and_rejects_10001():
    contacts = [{"email": f"c{i}@example.com"} for i in range(10000)]
    assert len(BulkContactsCreate(contacts=contacts).contacts) == 10000
    with pytest.raises(ValidationError) as exc:
        BulkContactsCreate(contacts=[*contacts, {"email": "extra@example.com"}])
    assert exc.value.errors()[0]["type"] == "too_long"


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
async def test_file_import_expands_before_billing_and_persistence(extension):
    if extension == "csv":
        content = 'email,company\r\n"a@example.com;\nb@example.com",Компания'.encode()
    else:
        book = Workbook()
        book.active.append(["email", "company"])
        book.active.append(["a@example.com;\nb@example.com", "Компания"])
        output = io.BytesIO()
        book.save(output)
        content = output.getvalue()
    _, rows = FileService.parse_content(f"contacts.{extension}", content)
    assert len(prepare_import_rows(rows)[0]) == 2
    tenant = SimpleNamespace(workspace_id=uuid4(), user=SimpleNamespace(id=uuid4()))
    with (
        patch("app.modules.contacts.router.ContactService") as service,
        patch("app.modules.contacts.router.BillingService") as billing,
        patch("app.modules.contacts.router.publish_enterprise_event", new_callable=AsyncMock),
    ):
        billing.return_value.check_limits = AsyncMock()
        service.return_value.bulk = AsyncMock(
            return_value=BulkResult(created=2, skipped=0, errors=[])
        )
        result = await import_contacts(
            UploadFile(filename=f"contacts.{extension}", file=io.BytesIO(content)),
            tenant,
            AsyncMock(),
        )
        assert result.created == 2 and result.errors == []
        billing.return_value.check_limits.assert_awaited_once_with("create_contact", 2)
        items = service.return_value.bulk.call_args.args[0]
        assert [str(c.email) for c in items] == ["a@example.com", "b@example.com"]
        assert all(c.company == "Компания" for c in items)
