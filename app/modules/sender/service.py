import base64
import logging
import re
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage as MIMEMessage
from email.utils import formataddr
from uuid import UUID

import aiosmtplib
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AppError, NotFoundError
from app.integrations.resilience import IntegrationError
from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.contacts.models import Contact
from app.modules.domains.models import SendingDomain
from app.modules.products.models import Product
from app.modules.sender.models import EmailMessage
from app.modules.sender.repository import MessageRepository
from app.modules.sender.schemas import SendEmailRequest
from app.modules.warmup.models import WarmupPlan
from app.shared.email_footer import with_unsubscribe_footer, with_unsubscribe_text
from app.shared.smtp import smtp_security_options

logger = logging.getLogger(__name__)


class SenderService:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.repo, self.workspace_id, self.settings = (
            MessageRepository(db, workspace_id),
            workspace_id,
            get_settings(),
        )
        from app.modules.billing.service import BillingService

        self.billing = BillingService(db, workspace_id)

    def build_mime(self, data: SendEmailRequest, message_id: UUID) -> MIMEMessage:
        message = MIMEMessage()
        message["From"] = formataddr((data.sender_name, str(data.sender_email)))
        message["To"] = str(data.to)
        message["Subject"] = data.subject
        message["X-App-Message-ID"] = str(message_id)
        unsubscribe = f"{self.settings.public_base_url.rstrip('/')}/api/v1/unsubscribe/{message_id}"
        message["List-Unsubscribe"] = f"<{unsubscribe}>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        pixel = (
            f'<img src="{self.settings.public_base_url}/api/v1/track/open/{message_id}.png" '
            'width="1" height="1" alt="" style="display:none">'
        )
        tracked_html = self._track_links(data.html, message_id)
        message.set_content(with_unsubscribe_text(data.text, unsubscribe))
        message.add_alternative(
            with_unsubscribe_footer(tracked_html, unsubscribe) + pixel, subtype="html"
        )
        return message

    def _track_links(self, html_body: str, message_id: UUID) -> str:
        pattern = re.compile(r'href=(["\'])(https?://[^"\']+)\1', re.IGNORECASE)

        def replace(match: re.Match[str]) -> str:
            if match.group(2).startswith(
                self.settings.public_base_url.rstrip("/") + "/api/v1/unsubscribe/"
            ):
                return match.group()  # An opt-out must never be counted as a marketing click.
            encoded = base64.urlsafe_b64encode(match.group(2).encode()).decode().rstrip("=")
            tracking_url = (
                f"{self.settings.public_base_url}/api/v1/track/click/{message_id}?url={encoded}"
            )
            quote = match.group(1)
            return f"href={quote}{tracking_url}{quote}"

        return pattern.sub(replace, html_body)

    async def _check_domain_rate(self, sender_email: str) -> None:
        domain = sender_email.rsplit("@", 1)[-1].casefold()
        registered = await self.repo.db.scalar(
            select(SendingDomain)
            .where(
                SendingDomain.workspace_id == self.workspace_id,
                SendingDomain.domain == domain,
            )
            .with_for_update()
        )
        if registered:
            today = datetime.now(UTC).date()
            if registered.daily_count_date != today:
                registered.current_daily_count = 0
                registered.daily_count_date = today
            warmup = await self.repo.db.scalar(
                select(WarmupPlan).where(WarmupPlan.domain_id == registered.id)
            )
            effective_limit = min(
                registered.daily_limit,
                (
                    warmup.current_daily_limit
                    if warmup and warmup.status == "active"
                    else registered.daily_limit
                ),
            )
            if registered.current_daily_count >= effective_limit:
                raise AppError(
                    f"Дневной лимит {effective_limit} писем для домена {domain} исчерпан"
                )
            registered.current_daily_count += 1
        redis = Redis.from_url(self.settings.redis_url)
        bucket = datetime.now(UTC).strftime("%Y%m%d%H")
        key = f"rate:sender-domain:{domain}:{bucket}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 3700)
        await redis.aclose()
        if count > 50:
            raise AppError(f"Лимит 50 писем/час для домена {domain} исчерпан")

    async def send(self, data: SendEmailRequest) -> EmailMessage:
        campaign, contact = await self._validate_scope(data)
        billing = getattr(self, "billing", None)
        if billing:
            await billing.check_limits("send_email")
        await self._check_domain_rate(str(data.sender_email))
        await self._ensure_bitrix_lead(data, campaign=campaign, contact=contact)
        row = await self.repo.add(
            EmailMessage(
                workspace_id=self.workspace_id,
                campaign_id=data.campaign_id,
                contact_id=contact.id if contact else data.contact_id,
                recipient_email=str(data.to),
                subject=data.subject,
            )
        )
        try:
            mime = self.build_mime(data, row.id)
            if getattr(self.settings, "email_provider", "smtp").casefold() == "ses":
                from app.modules.ses.client import SESClient

                row.provider_message_id = await SESClient(self.settings).send_raw_email(mime)
            else:
                response = await aiosmtplib.send(
                    mime,
                    hostname=self.settings.smtp_host,
                    port=self.settings.smtp_port,
                    username=self.settings.smtp_username or None,
                    password=self.settings.smtp_password or None,
                    **smtp_security_options(self.settings.smtp_port, self.settings.smtp_use_tls),
                    timeout=30,
                )
                row.provider_message_id = str(response[1])
            row.status = "sent"
            row.sent_at = datetime.now(UTC)
            if billing:
                from app.core.events import IntegrationEvent, publish_enterprise_event

                await publish_enterprise_event(
                    self.repo.db,
                    IntegrationEvent(
                        workspace_id=self.workspace_id,
                        resource_type="email",
                        resource_id=row.id,
                        data={
                            "recipient": row.recipient_email,
                            "campaign_id": str(row.campaign_id) if row.campaign_id else None,
                        },
                        kind="email.sent",
                    ),
                )
            if campaign:
                campaign.sent_count += 1
            if contact:
                bitrix_url = getattr(self.settings, "bitrix24_webhook_url", "")
                if (
                    contact
                    and isinstance(contact.bitrix_lead_id, int)
                    and isinstance(bitrix_url, str)
                    and bitrix_url
                ):
                    from app.modules.bitrix24.service import Bitrix24SyncService

                    try:
                        await Bitrix24SyncService(
                            self.repo.db, self.workspace_id
                        ).log_email_activity(
                            contact,
                            data.subject,
                            data.html,
                            row.provider_message_id or str(row.id),
                        )
                    except Exception:
                        logger.exception(
                            "Bitrix24 activity failed for email_message=%s; queueing retry",
                            row.id,
                        )
                        try:
                            from app.celery_app import celery_app

                            celery_app.send_task(
                                "app.modules.bitrix24.tasks.create_bitrix_activity",
                                args=[
                                    str(self.workspace_id),
                                    str(contact.id),
                                    data.subject,
                                    data.html,
                                    row.provider_message_id or str(row.id),
                                ],
                                queue="bitrix",
                            )
                        except Exception:
                            logger.exception(
                                "Unable to enqueue Bitrix24 retry for email_message=%s", row.id
                            )
        except (
            aiosmtplib.SMTPAuthenticationError,
            aiosmtplib.SMTPRecipientsRefused,
            TimeoutError,
            OSError,
            smtplib.SMTPException,
            IntegrationError,
        ) as exc:
            row.status = "failed"
            row.error = str(exc)
            if billing:
                from app.core.events import IntegrationEvent, publish_enterprise_event

                await publish_enterprise_event(
                    self.repo.db,
                    IntegrationEvent(
                        workspace_id=self.workspace_id,
                        resource_type="email",
                        resource_id=row.id,
                        data={"message": str(exc), "recipient": row.recipient_email},
                        kind="email.failed",
                    ),
                )
            raise
        return row

    async def _validate_scope(
        self, data: SendEmailRequest
    ) -> tuple[Campaign | None, Contact | None]:
        campaign = None
        contact = None
        if data.campaign_id:
            campaign = await self.repo.db.scalar(
                select(Campaign).where(
                    Campaign.id == data.campaign_id,
                    Campaign.workspace_id == self.workspace_id,
                )
            )
            if not campaign:
                raise NotFoundError("Кампания не найдена")
        if data.contact_id:
            contact = await self.repo.db.scalar(
                select(Contact).where(
                    Contact.id == data.contact_id,
                    Contact.workspace_id == self.workspace_id,
                )
            )
            if not contact or contact.email.casefold() != str(data.to).casefold():
                raise NotFoundError("Контакт не найден")
        else:
            existing = await self.repo.db.scalar(
                select(Contact).where(
                    Contact.workspace_id == self.workspace_id,
                    Contact.email == str(data.to).lower(),
                )
            )
            contact = existing if isinstance(existing, Contact) else None
        if contact and contact.is_unsubscribed is True:
            raise AppError("Получатель отписался от рассылки. Отправка запрещена.")
        if campaign and contact:
            linked = await self.repo.db.scalar(
                select(CampaignContact.id).where(
                    CampaignContact.campaign_id == campaign.id,
                    CampaignContact.contact_id == contact.id,
                )
            )
            if not linked:
                raise NotFoundError("Контакт не включён в кампанию")
        return campaign, contact

    async def _ensure_bitrix_lead(
        self,
        data: SendEmailRequest,
        *,
        campaign: Campaign | None = None,
        contact: Contact | None = None,
    ) -> None:
        webhook_url = getattr(self.settings, "bitrix24_webhook_url", "")
        if (
            not isinstance(webhook_url, str)
            or not webhook_url
            or not data.contact_id
            or not data.campaign_id
        ):
            return
        if contact is None:
            contact = await self.repo.db.get(Contact, data.contact_id)
            if not contact or contact.workspace_id != self.workspace_id:
                return
        if contact.bitrix_lead_id:
            return
        if campaign is None:
            campaign = await self.repo.db.get(Campaign, data.campaign_id)
            if not campaign or campaign.workspace_id != self.workspace_id:
                return
        product = await self.repo.db.get(Product, campaign.product_id)
        if not product or product.workspace_id != self.workspace_id:
            return
        from app.modules.bitrix24.service import Bitrix24SyncService

        await Bitrix24SyncService(self.repo.db, self.workspace_id).sync_contact_to_lead(
            contact, product, campaign.id
        )
