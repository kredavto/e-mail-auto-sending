from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.events import IntegrationEvent, publish_enterprise_event
from app.integrations.resilience import IntegrationError, with_retry
from app.modules.campaigns.models import Campaign
from app.modules.contacts.models import Contact
from app.modules.sender.models import EmailMessage
from app.modules.ses.sns import SNSSignatureVerifier

logger = logging.getLogger(__name__)


class SESWebhookHandler:
    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    async def _unwrap(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not payload.get("Type"):
            raise IntegrationError("SES webhooks require a signed SNS envelope")
        await SNSSignatureVerifier().verify(payload)
        configured_topic = self.settings.ses_sns_topic_arn
        if not configured_topic:
            raise IntegrationError("SES_SNS_TOPIC_ARN is required")
        if payload.get("TopicArn") != configured_topic:
            raise IntegrationError("Unexpected SNS topic")
        if payload.get("Type") == "SubscriptionConfirmation":
            return None
        if payload.get("Type") == "Notification" and isinstance(payload.get("Message"), str):
            message = json.loads(payload["Message"])
            if not isinstance(message, dict):
                raise IntegrationError("Invalid SNS Message")
            return message
        raise IntegrationError("Unsupported SNS envelope")

    async def handle(self, payload: dict[str, Any]) -> str:
        notification = await self._unwrap(payload)
        if notification is None:
            await self._confirm_subscription(payload)
            return "subscription_confirmed"
        notification_type = str(
            notification.get("notificationType") or notification.get("eventType") or ""
        ).casefold()
        if notification_type == "delivery":
            await self._handle_delivery(notification)
        elif notification_type == "bounce":
            await self._handle_bounce(notification)
        elif notification_type == "complaint":
            await self._handle_complaint(notification)
        else:
            return "ignored"
        return notification_type

    async def _confirm_subscription(self, payload: dict[str, Any]) -> None:
        url = str(payload.get("SubscribeURL", ""))
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").casefold()
        if (
            parsed.scheme != "https"
            or not hostname.startswith("sns.")
            or not hostname.endswith(".amazonaws.com")
        ):
            raise IntegrationError("Untrusted SNS subscription URL")

        async def confirm() -> None:
            logger.info(
                "external_request provider=sns method=GET host=%s path=%s",
                hostname,
                parsed.path,
            )
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url)
                if response.status_code >= 400:
                    raise IntegrationError(
                        f"SNS subscription confirmation failed with HTTP {response.status_code}"
                    )

        await with_retry(confirm, attempts=self.settings.integration_max_retries)

    async def _message(self, payload: dict[str, Any]) -> EmailMessage | None:
        mail = payload.get("mail", {})
        if not isinstance(mail, dict) or not mail.get("messageId"):
            raise IntegrationError("SES notification does not contain mail.messageId")
        return cast(
            EmailMessage | None,
            await self.db.scalar(
                select(EmailMessage).where(
                    EmailMessage.provider_message_id == str(mail["messageId"])
                )
            ),
        )

    @staticmethod
    def _event_time(section: object) -> datetime:
        if isinstance(section, dict) and isinstance(section.get("timestamp"), str):
            try:
                return datetime.fromisoformat(section["timestamp"].replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(UTC)

    async def _handle_delivery(self, payload: dict[str, Any]) -> None:
        message = await self._message(payload)
        if message:
            message.status = "delivered"
            message.delivered_at = self._event_time(payload.get("delivery"))

    async def _handle_bounce(self, payload: dict[str, Any]) -> None:
        message = await self._message(payload)
        if not message:
            return
        bounce = payload.get("bounce", {})
        bounce_type = (
            str(bounce.get("bounceType", "Unknown")) if isinstance(bounce, dict) else "Unknown"
        )
        message.status = "bounced"
        message.bounced = True
        message.bounce_type = bounce_type
        message.bounced_at = self._event_time(bounce)
        if message.campaign_id:
            campaign = await self.db.get(Campaign, message.campaign_id)
            if campaign:
                campaign.bounced_count += 1
        if message.contact_id:
            contact = await self.db.get(Contact, message.contact_id)
            if contact:
                if bounce_type.casefold() == "permanent":
                    contact.status = "unsubscribed"
                    contact.is_unsubscribed = True
                else:
                    contact.status = "bounced"
        await publish_enterprise_event(
            self.db,
            IntegrationEvent(
                workspace_id=message.workspace_id,
                resource_type="email",
                resource_id=message.id,
                data={
                    "bounce_type": bounce_type,
                    "campaign_id": str(message.campaign_id) if message.campaign_id else None,
                    "contact_id": str(message.contact_id) if message.contact_id else None,
                },
                kind="email.bounced",
            ),
        )

    async def _handle_complaint(self, payload: dict[str, Any]) -> None:
        message = await self._message(payload)
        if not message:
            return
        message.status = "complained"
        message.complained_at = self._event_time(payload.get("complaint"))
        if message.contact_id:
            contact = await self.db.get(Contact, message.contact_id)
            if contact:
                contact.status = "unsubscribed"
                contact.is_unsubscribed = True
        await publish_enterprise_event(
            self.db,
            IntegrationEvent(
                workspace_id=message.workspace_id,
                resource_type="email",
                resource_id=message.id,
                data={
                    "campaign_id": str(message.campaign_id) if message.campaign_id else None,
                    "contact_id": str(message.contact_id) if message.contact_id else None,
                },
                kind="email.complained",
            ),
        )
