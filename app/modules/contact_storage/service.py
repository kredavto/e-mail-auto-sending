import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.contacts.lists import list_tag
from app.modules.contacts.models import Contact, Segment


def table_name(name: str, base_id: UUID) -> str:
    """Preserve the readable base name within Postgres's 63-byte identifier limit."""
    slug = re.sub(r"[^\w]+", "_", name.casefold(), flags=re.UNICODE).strip("_") or "contacts"
    slug = slug.encode("utf-8")[:25].decode("utf-8", errors="ignore")
    return f"{slug}__{base_id.hex}"


def contact_data(contact: Contact) -> dict:
    data = {column.name: getattr(contact, column.name) for column in Contact.__table__.columns}
    return json.loads(
        json.dumps(
            data,
            default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value),
        )
    )


class ContactStorage:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def sync_base(self, base: Segment, client: httpx.AsyncClient) -> int:
        table = table_name(base.name, base.id)
        scope = {
            "workspace_id": str(base.workspace_id),
            "base_id": str(base.id),
            "run_id": str(uuid4()),
            "table_name": table,
            "name": base.name,
        }

        async def send(action: str, **data):
            response = await client.post(
                self.settings.supabase_contact_storage_url,
                json={**scope, "action": action, **data},
            )
            response.raise_for_status()
            return response.json()

        await send("begin")
        total = 0
        cursor = None
        while True:
            query = (
                select(Contact)
                .where(
                    Contact.workspace_id == base.workspace_id,
                    Contact.tags.contains([list_tag(base.id)]),
                )
                .order_by(Contact.id)
                .limit(500)
            )
            if cursor is not None:
                query = query.where(Contact.id > cursor)
            contacts = list((await self.db.scalars(query)).all())
            if not contacts:
                break
            await send("batch", contacts=[contact_data(contact) for contact in contacts])
            total += len(contacts)
            cursor = contacts[-1].id
        await send("finish", expected_count=total)
        return total

    async def sync_all(self, workspace_id: UUID | None = None, base_id: UUID | None = None) -> dict:
        if not self.settings.supabase_contact_storage_url:
            return {"status": "disabled"}
        filters = [Segment.filters["kind"].astext == "contact_list"]
        if workspace_id is not None:
            filters.append(Segment.workspace_id == workspace_id)
        if base_id is not None:
            filters.append(Segment.id == base_id)
        bases = list(
            (await self.db.scalars(select(Segment).where(*filters).order_by(Segment.id))).all()
        )
        count = 0
        async with httpx.AsyncClient(
            headers={
                "Authorization": "Bearer "
                + self.settings.supabase_contact_storage_token.get_secret_value()
            },
            timeout=60,
        ) as client:
            for base in bases:
                fingerprint = (
                    await self.db.execute(
                        select(func.count(Contact.id), func.max(Contact.updated_at)).where(
                            Contact.workspace_id == base.workspace_id,
                            Contact.tags.contains([list_tag(base.id)]),
                        )
                    )
                ).one()
                signature = f"{base.name}:{fingerprint[0]}:{fingerprint[1]}"
                if base.filters.get("supabase_signature") == signature:
                    continue
                copied = await self.sync_base(base, client)
                count += copied
                base.filters = {
                    **base.filters,
                    "supabase_signature": signature,
                    "supabase_synced_at": datetime.now(UTC).isoformat(),
                    "supabase_count": copied,
                }
        return {"status": "synced", "bases": len(bases), "contacts": count}
