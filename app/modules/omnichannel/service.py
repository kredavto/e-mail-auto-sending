from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from jinja2 import Environment, StrictUndefined, select_autoescape
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ab_testing.models import ABTest, ABTestVariant
from app.modules.ab_testing.service import ABTestingService
from app.modules.campaigns.models import Campaign
from app.modules.contacts.models import Contact
from app.modules.contacts.personalization import contact_variables
from app.modules.linkedin.models import LinkedInProfile
from app.modules.omnichannel.models import OmnichannelEvent
from app.modules.products.models import Product
from app.modules.sender.schemas import SendEmailRequest
from app.modules.sender.service import SenderService
from app.modules.sequences.models import SequenceStep
from app.modules.templates.models import Template
from app.modules.tenchat.service import TenchatService


@dataclass(frozen=True)
class StepResult:
    status: str
    channel: str
    reason: str | None = None
    message_id: str | None = None


class OmnichannelOrchestrator:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.tenchat = TenchatService(db, workspace_id)

    async def execute_step(
        self, contact: Contact, step: SequenceStep, product: Product, campaign: Campaign
    ) -> StepResult:
        if await self._has_replied_in_any_channel(contact):
            result = StepResult("skipped", step.step_type, "already_replied")
            await self._record(contact, step, step.step_type, result)
            return result

        requested = step.step_type
        try:
            if requested == "tenchat_message":
                profile = await self.tenchat.get_profile_for_contact(contact.id)
                if profile:
                    text = await self._render_text(contact, step, product)
                    message = await self.tenchat.send_outreach(profile, text)
                    result = StepResult("sent", "tenchat", message_id=str(message.id))
                else:
                    result = await self._send_email(
                        contact, step, product, campaign, "no_tenchat_profile"
                    )
            elif requested == "linkedin_message":
                profile = await self.db.scalar(
                    select(LinkedInProfile.id).where(
                        LinkedInProfile.workspace_id == self.workspace_id,
                        LinkedInProfile.contact_id == contact.id,
                    )
                )
                reason = "linkedin_outreach_api_unavailable" if profile else "no_linkedin_profile"
                result = await self._send_email(contact, step, product, campaign, reason)
            else:
                result = await self._send_email(contact, step, product, campaign)
            await self._record(contact, step, requested, result)
            return result
        except Exception as exc:
            result = StepResult("failed", requested, str(exc))
            await self._record(contact, step, requested, result, error=str(exc))
            raise

    async def _send_email(
        self,
        contact: Contact,
        step: SequenceStep,
        product: Product,
        campaign: Campaign,
        fallback_reason: str | None = None,
    ) -> StepResult:
        template = await self.db.get(Template, step.template_id) if step.template_id else None
        variant = await self._ab_variant(campaign.id, contact.id)
        if variant and variant.template_id:
            template = await self.db.get(Template, variant.template_id)
        context = contact_variables(contact, product.name)
        environment = Environment(
            autoescape=select_autoescape(default=True), undefined=StrictUndefined
        )
        config = step.config or {}
        subject_source = str(config.get("subject_override", "")) or (
            variant.subject
            if variant and variant.subject
            else (template.subject_template if template else str(config.get("subject", "")))
        )
        html_source = (
            template.html_body if template else str(config.get("html", config.get("text", "")))
        )
        text_source = template.text_body if template else str(config.get("text", ""))
        row = await SenderService(self.db, self.workspace_id).send(
            SendEmailRequest(
                to=contact.email,
                subject=environment.from_string(subject_source).render(**context),
                html=environment.from_string(html_source).render(**context),
                text=environment.from_string(text_source).render(**context),
                sender_email=campaign.sender_email,
                sender_name=(
                    variant.sender_name if variant and variant.sender_name else campaign.sender_name
                ),
                campaign_id=campaign.id,
                contact_id=contact.id,
            )
        )
        return StepResult("sent", "email", fallback_reason, str(row.id))

    async def _ab_variant(self, campaign_id: UUID, contact_id: UUID) -> ABTestVariant | None:
        test = await self.db.scalar(
            select(ABTest)
            .where(
                ABTest.campaign_id == campaign_id,
                ABTest.workspace_id == self.workspace_id,
                ABTest.status == "running",
            )
            .order_by(ABTest.created_at.desc())
            .limit(1)
        )
        if not test:
            return None
        assignment = await ABTestingService(self.db, self.workspace_id).assignment(
            test.id, contact_id
        )
        variant_key = assignment.variant_key
        if not variant_key:
            return None
        return cast(
            ABTestVariant | None,
            await self.db.scalar(
                select(ABTestVariant).where(
                    ABTestVariant.test_id == test.id,
                    ABTestVariant.variant_key == variant_key,
                )
            ),
        )

    async def _render_text(self, contact: Contact, step: SequenceStep, product: Product) -> str:
        template = await self.db.get(Template, step.template_id) if step.template_id else None
        source = template.text_body if template else str((step.config or {}).get("text", ""))
        return (
            Environment(undefined=StrictUndefined)
            .from_string(source)
            .render(
                **contact_variables(contact, product.name),
            )
        )

    async def _has_replied_in_any_channel(self, contact: Contact) -> bool:
        return contact.has_replied or await self.tenchat.has_replies(contact.id)

    async def _record(
        self,
        contact: Contact,
        step: SequenceStep,
        requested: str,
        result: StepResult,
        error: str | None = None,
    ) -> None:
        self.db.add(
            OmnichannelEvent(
                workspace_id=self.workspace_id,
                contact_id=contact.id,
                sequence_step_id=step.id,
                requested_channel=requested,
                actual_channel=result.channel,
                status=result.status,
                reason=result.reason,
                provider_message_id=result.message_id,
                error_message=error,
            )
        )

    async def channels(self, contact_id: UUID) -> dict[str, object]:
        contact = await self.db.get(Contact, contact_id)
        tenchat = await self.tenchat.get_profile_for_contact(contact_id)
        linkedin = await self.db.scalar(
            select(LinkedInProfile.id).where(
                LinkedInProfile.workspace_id == self.workspace_id,
                LinkedInProfile.contact_id == contact_id,
            )
        )
        return {
            "contact_id": str(contact_id),
            "email": bool(contact and contact.email),
            "tenchat": bool(tenchat),
            "linkedin": bool(linkedin),
            "has_replied": bool(contact and contact.has_replied),
        }

    async def stats(self) -> dict[str, int]:
        result = await self.db.execute(
            select(OmnichannelEvent.actual_channel, func.count())
            .where(OmnichannelEvent.workspace_id == self.workspace_id)
            .group_by(OmnichannelEvent.actual_channel)
        )
        return {str(channel): int(count) for channel, count in result.all()}
