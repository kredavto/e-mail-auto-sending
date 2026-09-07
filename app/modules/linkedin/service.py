from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.service import BillingService
from app.modules.contacts.models import Contact
from app.modules.hunter.service import HunterService
from app.modules.linkedin.client import LinkedInClient
from app.modules.linkedin.models import LinkedInExport, LinkedInProfile
from app.modules.linkedin.parser import SalesNavigatorParser


class LinkedInService:
    def __init__(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        *,
        client: LinkedInClient | None = None,
        hunter: HunterService | None = None,
        billing: BillingService | None = None,
    ) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.client = client or LinkedInClient()
        self.hunter = hunter or HunterService()
        self.billing = billing or BillingService(db, workspace_id)

    async def process_export(self, export: LinkedInExport, csv_content: str) -> int:
        try:
            rows = SalesNavigatorParser().parse(csv_content)
            export.total_rows = len(rows)
            imported = 0
            for data in rows:
                profile = await self.db.scalar(
                    select(LinkedInProfile).where(
                        LinkedInProfile.workspace_id == self.workspace_id,
                        LinkedInProfile.linkedin_id == data["linkedin_id"],
                    )
                )
                if profile:
                    for key, value in data.items():
                        setattr(profile, key, value or getattr(profile, key))
                else:
                    self.db.add(LinkedInProfile(workspace_id=self.workspace_id, **data))
                imported += 1
            export.imported_rows = imported
            export.status = "completed"
            return imported
        except Exception as exc:
            export.status = "failed"
            export.error_message = str(exc)
            raise

    async def enrich_emails(self, profile_ids: list[UUID] | None = None) -> dict[str, int]:
        query = select(LinkedInProfile).where(
            LinkedInProfile.workspace_id == self.workspace_id,
            LinkedInProfile.email.is_(None),
        )
        if profile_ids:
            query = query.where(LinkedInProfile.id.in_(profile_ids))
        profiles = list((await self.db.scalars(query)).all())
        enriched = 0
        skipped = 0
        for profile in profiles:
            if not profile.company_domain:
                skipped += 1
                continue
            result = await self.hunter.find_confident_email(
                profile.company_domain, profile.first_name, profile.last_name
            )
            if not result:
                skipped += 1
                continue
            profile.email = str(result["email"])
            profile.email_confidence = int(str(result["confidence"]))
            contact = await self.db.scalar(
                select(Contact).where(
                    Contact.workspace_id == self.workspace_id, Contact.email == profile.email
                )
            )
            if not contact:
                await self.billing.reserve_quota("create_contact")
                contact = Contact(
                    workspace_id=self.workspace_id,
                    email=profile.email,
                    first_name=profile.first_name,
                    last_name=profile.last_name,
                    full_name=f"{profile.first_name} {profile.last_name}".strip(),
                    company=profile.company_name,
                    position=profile.headline or "",
                    industry=profile.industry or None,
                    source="linkedin",
                    linkedin_url=profile.profile_url,
                )
                self.db.add(contact)
                await self.db.flush()
            profile.contact_id = contact.id
            enriched += 1
        return {"enriched": enriched, "skipped": skipped}

    async def sync_lead_gen_forms(self, ad_account_id: str) -> dict[str, int]:
        forms = await self.client.get_lead_gen_forms(ad_account_id)
        leads = 0
        for form in forms:
            form_id = str(form.get("id") or form.get("urn") or "")
            if not form_id:
                continue
            responses = await self.client.get_form_leads(form_id)
            for response in responses:
                values = self._lead_values(response)
                email = values.get("email", "").casefold()
                if not email:
                    continue
                existing = await self.db.scalar(
                    select(Contact).where(
                        Contact.workspace_id == self.workspace_id, Contact.email == email
                    )
                )
                if not existing:
                    await self.billing.reserve_quota("create_contact")
                    self.db.add(
                        Contact(
                            workspace_id=self.workspace_id,
                            email=email,
                            first_name=values.get("first_name", ""),
                            last_name=values.get("last_name", ""),
                            full_name=values.get("full_name", ""),
                            company=values.get("company", ""),
                            source="linkedin_lead_gen",
                        )
                    )
                leads += 1
        return {"forms": len(forms), "leads": leads}

    @staticmethod
    def _lead_values(response: dict[str, object]) -> dict[str, str]:
        output: dict[str, str] = {}
        answers = response.get("answers", [])
        if isinstance(answers, list):
            for item in answers:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("questionId") or item.get("name") or "").casefold()
                value = str(item.get("answerDetails") or item.get("value") or "")
                if "email" in key:
                    output["email"] = value
                elif "first" in key:
                    output["first_name"] = value
                elif "last" in key:
                    output["last_name"] = value
                elif "company" in key:
                    output["company"] = value
        return output
