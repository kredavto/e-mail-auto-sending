from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import IntegrationEvent, publish_enterprise_event
from app.modules.bitrix24.client import Bitrix24Client, BitrixError
from app.modules.bitrix24.models import BitrixSyncLog
from app.modules.campaigns.models import CampaignContact
from app.modules.contacts.models import Contact
from app.modules.products.models import Product


class Bitrix24SyncService:
    def __init__(
        self, db: AsyncSession, workspace_id: UUID, client: Bitrix24Client | None = None
    ) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.client = client or Bitrix24Client()

    async def _log(
        self,
        entity_type: str,
        action: str,
        status: str,
        *,
        contact_id: UUID | None = None,
        entity_id: int | None = None,
        error: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self.db.add(
            BitrixSyncLog(
                workspace_id=self.workspace_id,
                contact_id=contact_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                status=status,
                error_message=error,
                details=details or {},
            )
        )

    async def sync_contact_to_lead(
        self, contact: Contact, product: Product, campaign_id: UUID | None = None
    ) -> int:
        try:
            existing = await self.client.find_lead_by_email(contact.email)
            fields = self._to_bitrix_fields(contact, product, campaign_id)
            if existing:
                lead_id = int(str(existing["ID"]))
                await self.client.update_lead(lead_id, fields)
                action = "update"
            else:
                lead_id = await self.client.create_lead(fields)
                action = "create"
            contact.bitrix_lead_id = lead_id
            contact.bitrix_synced_at = datetime.now(UTC)
            await self._log("lead", action, "success", contact_id=contact.id, entity_id=lead_id)
            return lead_id
        except Exception as exc:
            await self._log("lead", "sync", "failed", contact_id=contact.id, error=str(exc))
            raise

    async def log_email_activity(
        self, contact: Contact, subject: str, html_body: str, message_id: str
    ) -> int:
        if not contact.bitrix_lead_id:
            raise BitrixError("lead_missing", "Contact has not been synchronized to Bitrix24")
        try:
            activity_id = await self.client.create_email_activity(
                owner_id=contact.bitrix_lead_id,
                owner_type="L",
                subject=subject,
                description=html_body,
                direction="O",
                message_id=message_id,
            )
            await self._log(
                "activity", "create", "success", contact_id=contact.id, entity_id=activity_id
            )
            return activity_id
        except Exception as exc:
            await self._log("activity", "create", "failed", contact_id=contact.id, error=str(exc))
            raise

    async def check_incoming_replies(self) -> list[dict[str, object]]:
        since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        activities = await self.client.list_activities(
            {"TYPE_ID": 4, "DIRECTION": 1, ">=CREATED": since}
        )
        lead_ids = {
            int(str(row["OWNER_ID"]))
            for row in activities
            if row.get("OWNER_ID") and str(row.get("OWNER_TYPE_ID", "")).upper() in {"1", "L"}
        }
        if lead_ids:
            contacts = list(
                (
                    await self.db.scalars(
                        select(Contact).where(
                            Contact.workspace_id == self.workspace_id,
                            Contact.bitrix_lead_id.in_(lead_ids),
                        )
                    )
                ).all()
            )
            for contact in contacts:
                was_replied = contact.has_replied
                contact.has_replied = True
                contact.status = "replied"
                await self.db.execute(
                    update(CampaignContact)
                    .where(
                        CampaignContact.contact_id == contact.id, CampaignContact.status == "active"
                    )
                    .values(status="stopped", next_send_at=None)
                )
                await self._log(
                    "activity",
                    "read",
                    "success",
                    contact_id=contact.id,
                    entity_id=contact.bitrix_lead_id,
                )
                if not was_replied:
                    await publish_enterprise_event(
                        self.db,
                        IntegrationEvent(
                            workspace_id=self.workspace_id,
                            resource_type="contact",
                            resource_id=contact.id,
                            data={"email": contact.email, "channel": "bitrix24"},
                            kind="contact.replied",
                        ),
                    )
        return activities

    async def sync_statuses(self) -> int:
        contacts = list(
            (
                await self.db.scalars(
                    select(Contact).where(
                        Contact.workspace_id == self.workspace_id,
                        Contact.bitrix_lead_id.is_not(None),
                    )
                )
            ).all()
        )
        status_map = {
            "NEW": "new",
            "IN_PROCESS": "contacted",
            "PROCESSED": "qualified",
            "CONVERTED": "qualified",
            "JUNK": "unsubscribed",
        }
        changed = 0
        for contact in contacts:
            lead = await self.client.get_lead(int(contact.bitrix_lead_id or 0))
            remote = status_map.get(str((lead or {}).get("STATUS_ID", "")))
            if remote and remote != contact.status:
                contact.status = remote
                if remote == "unsubscribed":
                    contact.is_unsubscribed = True
                changed += 1
        return changed

    async def convert_lead_to_deal(self, contact: Contact, title: str) -> int:
        if not contact.bitrix_lead_id:
            raise BitrixError("lead_missing", "Contact has no Bitrix24 lead")
        deal_id = await self.client.create_deal(
            {"TITLE": title, "LEAD_ID": contact.bitrix_lead_id, "STAGE_ID": "NEW"}
        )
        await self.client.update_lead(contact.bitrix_lead_id, {"STATUS_ID": "CONVERTED"})
        await self._log("deal", "create", "success", contact_id=contact.id, entity_id=deal_id)
        return deal_id

    async def setup_fields(self) -> dict[str, int | str]:
        definitions = {
            "UF_MAILER_PRODUCT_ID": ("ID продукта Mailer", "string"),
            "UF_MAILER_PRODUCT_NAME": ("Продукт Mailer", "string"),
            "UF_MAILER_CAMPAIGN_ID": ("ID кампании Mailer", "string"),
        }
        result: dict[str, int | str] = {}
        for name, (label, field_type) in definitions.items():
            try:
                result[name] = await self.client.create_lead_user_field(
                    {
                        "FIELD_NAME": name.removeprefix("UF_"),
                        "EDIT_FORM_LABEL": {"ru": label, "en": label},
                        "LIST_COLUMN_LABEL": {"ru": label, "en": label},
                        "USER_TYPE_ID": field_type,
                    }
                )
            except BitrixError as exc:
                if exc.code in {"ERROR_CORE", "ERROR_FIELD_ALREADY_EXISTS"}:
                    result[name] = "already_exists"
                else:
                    raise
        return result

    async def stats(self) -> dict[str, int]:
        rows = await self.db.execute(
            select(BitrixSyncLog.status, func.count())
            .where(BitrixSyncLog.workspace_id == self.workspace_id)
            .group_by(BitrixSyncLog.status)
        )
        return {str(status): int(count) for status, count in rows.all()}

    @staticmethod
    def _to_bitrix_fields(
        contact: Contact, product: Product, campaign_id: UUID | None = None
    ) -> dict[str, object]:
        status_map = {
            "new": "NEW",
            "contacted": "IN_PROCESS",
            "replied": "PROCESSED",
            "qualified": "CONVERTED",
            "unsubscribed": "JUNK",
        }
        return {
            "TITLE": f"{product.name}: {contact.company}",
            "NAME": contact.first_name or "",
            "LAST_NAME": contact.last_name or "",
            "COMPANY_TITLE": contact.company,
            "POST": contact.position,
            "EMAIL": [{"VALUE": contact.email, "VALUE_TYPE": "WORK"}],
            "PHONE": ([{"VALUE": contact.phone, "VALUE_TYPE": "WORK"}] if contact.phone else []),
            "SOURCE_ID": "EMAIL",
            "STATUS_ID": status_map.get(contact.status, "NEW"),
            "OPENED": "Y",
            "UF_MAILER_PRODUCT_ID": str(product.id),
            "UF_MAILER_PRODUCT_NAME": product.name,
            "UF_MAILER_CAMPAIGN_ID": str(campaign_id) if campaign_id else "",
            "COMMENTS": f"Индустрия: {contact.industry or 'не указана'}",
        }
