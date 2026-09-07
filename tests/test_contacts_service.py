from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.contacts.models import Contact, Segment
from app.modules.contacts.schemas import ContactCreate, ContactUpdate, SegmentCreate
from app.modules.contacts.service import ContactService


class FakeContactRepository:
    def __init__(self) -> None:
        self.contacts: dict[str, Contact] = {}
        self.segments: list[Segment] = []

    async def by_email(self, email: str) -> Contact | None:
        return self.contacts.get(email)

    async def add(self, contact: Contact) -> Contact:
        contact.id = uuid4()
        self.contacts[contact.email] = contact
        return contact

    async def get(self, contact_id: object) -> Contact | None:
        return next((item for item in self.contacts.values() if item.id == contact_id), None)

    async def add_segment(self, segment: Segment) -> Segment:
        segment.id = uuid4()
        self.segments.append(segment)
        return segment

    async def list_all(self, offset: int = 0, limit: int = 50) -> tuple[list[Contact], int]:
        items = list(self.contacts.values())[offset : offset + limit]
        return items, len(self.contacts)


def service() -> tuple[ContactService, FakeContactRepository]:
    instance = ContactService(AsyncMock(), uuid4())
    repo = FakeContactRepository()
    instance.repo = repo  # type: ignore[assignment]
    return instance, repo


@pytest.mark.asyncio
async def test_create_parses_name_and_rejects_duplicate() -> None:
    contacts, _ = service()
    payload = ContactCreate(email="LEAD@example.com", full_name="Иванов Иван Иванович")
    created = await contacts.create(payload)
    assert created.email == "lead@example.com"
    assert (created.last_name, created.first_name, created.patronymic) == (
        "Иванов",
        "Иван",
        "Иванович",
    )
    with pytest.raises(ConflictError):
        await contacts.create(payload)


@pytest.mark.asyncio
async def test_update_and_missing_contact() -> None:
    contacts, _ = service()
    created = await contacts.create(
        ContactCreate(email="lead@example.com", full_name="Иван Иванов")
    )
    updated = await contacts.update(
        created.id, ContactUpdate(full_name="Петров Пётр", status="opened")
    )
    assert updated.last_name == "Петров"
    assert updated.status == "opened"
    with pytest.raises(NotFoundError):
        await contacts.update(uuid4(), ContactUpdate(company="Missing"))


@pytest.mark.asyncio
async def test_bulk_segment_and_export() -> None:
    contacts, repo = service()
    first = ContactCreate(email="one@example.com", full_name="Первый Лид", company="Альфа")
    result = await contacts.bulk([first, first, ContactCreate(email="two@example.com")])
    assert (result.created, result.skipped) == (2, 1)
    segment = await contacts.create_segment(SegmentCreate(name="IT", filters={"industry": "IT"}))
    assert segment.name == "IT"
    assert repo.segments == [segment]
    exported = await contacts.export_csv()
    assert "one@example.com" in exported
    assert "Альфа" in exported
