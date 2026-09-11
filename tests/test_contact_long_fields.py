from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.contacts.importing import prepare_import_rows
from app.modules.contacts.models import Contact
from app.modules.contacts.normalization import CONTACT_TEXT_LIMITS, normalize_contact_text
from app.modules.contacts.schemas import BulkContactsCreate, ContactCreate
from app.modules.contacts.service import ContactService


@pytest.mark.parametrize("field,limit", CONTACT_TEXT_LIMITS.items())
def test_long_optional_field_is_database_safe_and_preserved(field, limit):
    original = "Я" * (limit + 10)
    data = {"email": "a@example.com", field: original}
    contact = BulkContactsCreate(contacts=[data]).contacts[0]
    assert getattr(contact, field) == original[:limit]
    assert contact.custom_fields[f"import_original_{field}"] == original
    assert Contact.__table__.c[field].type.length == limit
    assert data[field] == original


def test_missing_and_invalid_email_do_not_discard_other_rows():
    rows = [
        {"email": "", "industry": "Я" * 500},
        {
            "email": "a@example.com;bad;b@example.com",
            "industry": "Я" * 500,
            "phone": "9" * 150,
            "full_name": None,
            "company": None,
        },
        {"email": "c@example.com", "first_name": "И" * 200},
    ]
    contacts, errors = prepare_import_rows(rows)
    assert [str(contact.email) for contact in contacts] == [
        "a@example.com",
        "b@example.com",
        "c@example.com",
    ]
    assert len(errors) == 2
    assert contacts[0].custom_fields["import_original_phone"] == "9" * 150


def test_originals_do_not_overwrite_custom_fields_and_normalization_is_idempotent():
    original = "Я" * 300
    data = {"industry": original, "custom_fields": {"import_original_industry": "existing"}}
    normalized = normalize_contact_text(data)
    assert normalized["custom_fields"] == {
        "import_original_industry": "existing",
        "import_original_industry_2": original,
    }
    assert normalize_contact_text(normalized) == normalized
    assert data["industry"] == original


async def test_service_also_normalizes_derived_name_parts_before_database_insert():
    service = ContactService(Mock(), uuid4())
    service.repo.by_email = AsyncMock(return_value=None)
    service.repo.add = AsyncMock(side_effect=lambda contact: contact)
    result = await service.create(ContactCreate(email="a@example.com", full_name="Я" * 240))
    for field, limit in CONTACT_TEXT_LIMITS.items():
        value = getattr(result, field)
        assert value is None or len(value) <= limit
    assert result.full_name == "Я" * 240
    assert any(value == "Я" * 240 for value in result.custom_fields.values())
