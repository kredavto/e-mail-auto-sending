import csv
import io
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.audit import audited
from app.modules.contacts.models import Contact, Segment
from app.modules.contacts.normalization import normalize_contact_text
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import BulkResult, ContactCreate, ContactUpdate, SegmentCreate
from app.shared.utils import normalize_email, parse_full_name


class ContactService:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.repo = ContactRepository(db, workspace_id)
        self.workspace_id = workspace_id

    async def create(self, data: ContactCreate) -> Contact:
        email = normalize_email(str(data.email))
        if await self.repo.by_email(email):
            raise ConflictError("Контакт с таким email уже существует")
        last_name, first_name, patronymic = parse_full_name(data.full_name)
        last_name = data.last_name if data.last_name is not None else last_name
        first_name = data.first_name if data.first_name is not None else first_name
        patronymic = data.patronymic if data.patronymic is not None else patronymic
        return await self.repo.add(
            Contact(
                **normalize_contact_text(
                    {
                        **data.model_dump(),
                        "workspace_id": self.workspace_id,
                        "email": email,
                        "last_name": last_name,
                        "first_name": first_name,
                        "patronymic": patronymic,
                    }
                ),
            )
        )

    @audited("contact.updated", "contact")
    async def update(self, contact_id: UUID, data: ContactUpdate) -> Contact:
        contact = await self.repo.get(contact_id)
        if not contact:
            raise NotFoundError("Контакт не найден")
        changes = data.model_dump(exclude_unset=True)
        if "full_name" in changes:
            contact.last_name, contact.first_name, contact.patronymic = parse_full_name(
                changes["full_name"]
            )
        for field, value in changes.items():
            setattr(contact, field, value)
        return contact

    async def bulk(self, items: list[ContactCreate]) -> BulkResult:
        created = skipped = 0
        errors: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(items, start=1):
            email = normalize_email(str(item.email))
            if email in seen or await self.repo.by_email(email):
                skipped += 1
                continue
            try:
                await self.create(item)
                seen.add(email)
                created += 1
            except Exception as exc:
                errors.append(f"Строка {index}: {exc}")
        return BulkResult(created=created, skipped=skipped, errors=errors)

    @audited("segment.created", "segment")
    async def create_segment(self, data: SegmentCreate) -> Segment:
        return await self.repo.add_segment(
            Segment(workspace_id=self.workspace_id, **data.model_dump())
        )

    async def export_csv(self) -> str:
        contacts, _ = await self.repo.list_all(limit=100_000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["email", "full_name", "company", "position", "industry", "status"])
        for item in contacts:
            writer.writerow(
                [
                    item.email,
                    item.full_name,
                    item.company,
                    item.position,
                    item.industry,
                    item.status,
                ]
            )
        return output.getvalue()
