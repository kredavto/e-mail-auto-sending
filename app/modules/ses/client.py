from __future__ import annotations

import asyncio
import logging
from email.message import Message
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings, get_settings
from app.integrations.resilience import IntegrationError, get_circuit_breaker, with_retry

logger = logging.getLogger(__name__)


class SESClient:
    def __init__(self, settings: Settings | None = None, sdk_client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        kwargs: dict[str, str] = {"region_name": self.settings.aws_region}
        if self.settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
        if self.settings.aws_session_token:
            kwargs["aws_session_token"] = self.settings.aws_session_token
        self.sdk = sdk_client or boto3.client("ses", **kwargs)
        self.circuit = get_circuit_breaker(
            "ses",
            self.settings.integration_circuit_failure_threshold,
            self.settings.integration_circuit_recovery_seconds,
        )

    async def _call(self, method: str, **kwargs: object) -> dict[str, Any]:
        async def operation() -> dict[str, Any]:
            logger.info("external_request provider=ses method=%s", method)
            try:
                result = await asyncio.to_thread(getattr(self.sdk, method), **kwargs)
                return dict(result)
            except (BotoCoreError, ClientError) as exc:
                raise IntegrationError(f"SES {method} failed: {exc}") from exc

        return await self.circuit.call(
            lambda: with_retry(operation, attempts=self.settings.integration_max_retries)
        )

    async def send_raw_email(self, mime: Message) -> str:
        params: dict[str, object] = {"RawMessage": {"Data": mime.as_bytes()}}
        sender = mime.get("From")
        if sender:
            params["Source"] = sender
        if self.settings.ses_configuration_set:
            params["ConfigurationSetName"] = self.settings.ses_configuration_set
        result = await self._call("send_raw_email", **params)
        return str(result["MessageId"])

    async def get_send_quota(self) -> dict[str, object]:
        result = await self._call("get_send_quota")
        return {
            "max_24_hour_send": result.get("Max24HourSend", 0),
            "max_send_rate": result.get("MaxSendRate", 0),
            "sent_last_24_hours": result.get("SentLast24Hours", 0),
        }

    async def get_send_statistics(self) -> list[dict[str, object]]:
        result = await self._call("get_send_statistics")
        return list(result.get("SendDataPoints", []))

    async def verify_domain_identity(self, domain: str) -> str:
        result = await self._call("verify_domain_identity", Domain=domain)
        return str(result["VerificationToken"])

    async def get_domain_verification(self, domain: str) -> str:
        result = await self._call("get_identity_verification_attributes", Identities=[domain])
        attributes = result.get("VerificationAttributes", {})
        if not isinstance(attributes, dict):
            return "NotStarted"
        domain_result = attributes.get(domain, {})
        return str(domain_result.get("VerificationStatus", "NotStarted"))
