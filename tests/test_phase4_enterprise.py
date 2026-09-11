import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.core.events import EventBus, IntegrationEvent
from app.modules.audit.service import _minimal_pdf, sanitize
from app.modules.billing.providers import PaymentProviderError, StripeProvider, TinkoffProvider
from app.modules.billing.service import BillingService, LimitExceededError
from app.modules.notifications.models import NotificationPreference
from app.modules.notifications.service import CRITICAL_TYPES, NotificationDispatcher
from app.modules.webhooks.models import Webhook, WebhookDelivery
from app.modules.webhooks.service import (
    UnsafeWebhookURLError,
    WebhookDeliveryError,
    WebhookDispatcher,
    canonical_payload,
    decrypt_secret,
    encrypt_secret,
    validate_webhook_url,
)
from app.modules.webhooks.tasks import deliver_webhook


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.messages.append((channel, payload))


@pytest.mark.asyncio
async def test_event_bus_publishes_and_isolates_handlers() -> None:
    good = SimpleNamespace(handle_event=AsyncMock())
    bad = SimpleNamespace(handle_event=AsyncMock(side_effect=RuntimeError("broken")))
    redis = FakeRedis()
    event = IntegrationEvent(workspace_id=uuid4(), kind="contact.created", data={"count": 1})
    await EventBus(redis, [bad, good]).publish(event)  # type: ignore[arg-type]
    assert redis.messages[0][0] == "events:contact.created"
    assert json.loads(redis.messages[0][1])["type"] == "contact.created"
    good.handle_event.assert_awaited_once_with(event)


def test_notification_critical_email_policy() -> None:
    assert "error" in CRITICAL_TYPES
    assert NotificationDispatcher._enabled(None, "email", "error")
    assert not NotificationDispatcher._enabled(None, "email", "campaign_started")
    preference = NotificationPreference(
        user_id=uuid4(),
        workspace_id=uuid4(),
        email_notifications={"campaign_started": True},
        webpush_notifications={"new_reply": True},
        telegram_notifications={},
    )
    assert NotificationDispatcher._enabled(preference, "email", "campaign_started")
    assert NotificationDispatcher._enabled(preference, "webpush", "new_reply")


def test_audit_redacts_nested_secrets_and_pdf_is_valid() -> None:
    value = sanitize(
        {"email": "user@example.com", "password": "secret", "nested": {"api_key": "123"}}
    )
    assert value == {
        "email": "user@example.com",
        "password": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]"},
    }
    pdf = _minimal_pdf(["Audit", "contact.created"])
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.endswith(b"%%EOF")


def test_webhook_hmac_and_secret_encryption() -> None:
    payload: dict[str, object] = {"b": 2, "a": 1}
    expected = hmac.new(b"secret", canonical_payload(payload), hashlib.sha256).hexdigest()
    assert WebhookDispatcher._sign_payload(payload, "secret") == f"sha256={expected}"
    encrypted = encrypt_secret("secret", "application-key")
    assert encrypted != "secret"
    assert decrypt_secret(encrypted, "application-key") == "secret"


def test_webhook_url_ssrf_policy_and_retry_count() -> None:
    validate_webhook_url("https://hooks.example.com/events")
    with pytest.raises(UnsafeWebhookURLError):
        validate_webhook_url("http://127.0.0.1/internal")
    with pytest.raises(UnsafeWebhookURLError):
        validate_webhook_url("https://169.254.169.254/latest/meta-data")
    assert deliver_webhook.max_retries == 4  # initial delivery + 4 retries = 5 attempts


class DeliveryDB:
    def __init__(self, delivery: WebhookDelivery, webhook: Webhook) -> None:
        self.delivery, self.webhook = delivery, webhook
        self.flush = AsyncMock()

    async def scalar(self, _query: object) -> WebhookDelivery:
        return self.delivery

    async def get(self, model: object, identifier: object) -> object | None:
        if model is WebhookDelivery and identifier == self.delivery.id:
            return self.delivery
        if model is Webhook and identifier == self.webhook.id:
            return self.webhook
        return None


@pytest.mark.asyncio
async def test_webhook_delivery_records_failed_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        app_secret_key="test-application-key",
        webhook_allow_private_urls=True,
    )
    webhook = Webhook(
        id=uuid4(),
        workspace_id=uuid4(),
        name="CRM",
        url="https://hooks.example.com/events",
        events=["contact.created"],
        secret=encrypt_secret("secret", settings.app_secret_key),
        is_active=True,
    )
    delivery = WebhookDelivery(
        id=uuid4(),
        webhook_id=webhook.id,
        event_id=uuid4(),
        event_type="contact.created",
        payload={"id": "evt", "data": {}},
        attempts=0,
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(503, text="unavailable"))
    async with httpx.AsyncClient(transport=transport) as client:
        dispatcher = WebhookDispatcher(
            DeliveryDB(delivery, webhook),  # type: ignore[arg-type]
            webhook.workspace_id,
            settings=settings,
            client=client,
        )
        with pytest.raises(WebhookDeliveryError):
            await dispatcher.deliver(delivery.id)
    assert delivery.attempts == 1
    assert delivery.response_status == 503
    assert delivery.success is False
    assert delivery.next_attempt_at is not None


class StubBilling(BillingService):
    def __init__(self, plan: str, current: int) -> None:
        self.plan, self.current = plan, current
        self.settings = Settings(_env_file=None, free_plan_test_mode=False)
        self.db = Mock()
        self.workspace_id = uuid4()
        self.repo = SimpleNamespace(subscription=AsyncMock(return_value=None))

    async def get_or_create_subscription(self) -> object:  # type: ignore[override]
        start, end = self.period_bounds(datetime(2026, 9, 7, tzinfo=UTC))
        return SimpleNamespace(
            plan=self.plan,
            id=uuid4(),
            status="active",
            current_period_start=start,
            current_period_end=end,
        )

    async def current_usage(self, metric: str, period_start: datetime) -> int:
        return self.current


@pytest.mark.asyncio
async def test_billing_limits_and_enterprise_unlimited() -> None:
    assert await StubBilling("free", 499).check_limits("send_email")
    with pytest.raises(LimitExceededError):
        await StubBilling("free", 500).check_limits("send_email")
    assert await StubBilling("enterprise", 10**9).check_limits("send_email", 10**9)


def test_stripe_signature_verification() -> None:
    secret = "whsec_test"
    body = json.dumps({"id": "evt_1", "type": "checkout.session.completed"}).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    settings = Settings(_env_file=None, stripe_webhook_secret=secret)
    provider = StripeProvider(settings)
    assert provider.verify_webhook(body, f"t={timestamp},v1={signature}")["id"] == "evt_1"
    with pytest.raises(PaymentProviderError):
        provider.verify_webhook(body, f"t={timestamp},v1=bad")


def test_tinkoff_signature_verification() -> None:
    settings = Settings(
        _env_file=None, tinkoff_terminal_key="terminal", tinkoff_password="password"
    )
    provider = TinkoffProvider(settings)
    payload: dict[str, object] = {
        "TerminalKey": "terminal",
        "PaymentId": "123",
        "Amount": 990000,
        "Status": "CONFIRMED",
        "Success": True,
    }
    payload["Token"] = provider.token(payload)
    provider.verify_webhook(payload)
    payload["Token"] = "invalid"
    with pytest.raises(PaymentProviderError):
        provider.verify_webhook(payload)


def test_phase4_openapi_routes() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/notifications",
        "/api/v1/notifications/unread-count",
        "/api/v1/audit/logs",
        "/api/v1/audit/export",
        "/api/v1/webhooks",
        "/api/v1/billing/subscription",
        "/api/v1/billing/webhook/yookassa",
        "/api/v1/billing/webhook/stripe",
        "/api/v1/billing/webhook/tinkoff",
    ):
        assert path in paths
