from __future__ import annotations

import asyncio
import inspect
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import httpcore
import httpx
import jwt
import pyotp
import pytest
from celery.exceptions import Retry
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.config import Settings, get_settings
from app.core.events import (
    ENTERPRISE_EVENT_TYPES,
    ENTERPRISE_HANDLER_REGISTRY,
    EventBus,
    IntegrationEvent,
    publish_enterprise_event,
)
from app.core.exceptions import AppError, AuthenticationError, NotFoundError
from app.core.security import create_refresh_token
from app.modules.audit.models import AuditLog, SecurityAuditEvent
from app.modules.audit.service import (
    AuditContext,
    AuditService,
    SecurityAuditSink,
    reset_audit_context,
    sanitize,
    set_audit_context,
)
from app.modules.auth.models import AuthSession
from app.modules.auth.schemas import LoginRequest, MFALoginRequest, TokenPair
from app.modules.auth.service import AuthService
from app.modules.billing.models import Invoice, PaymentEvent, Subscription
from app.modules.billing.providers import (
    PaymentProviderError,
    StripeProvider,
    TinkoffProvider,
    YooKassaProvider,
)
from app.modules.billing.schemas import SubscribeRequest
from app.modules.billing.service import BillingService, LimitExceededError
from app.modules.billing.tasks import rollover_billing_periods
from app.modules.campaigns.models import Campaign
from app.modules.contacts.models import Contact
from app.modules.linkedin.models import LinkedInProfile
from app.modules.linkedin.service import LinkedInService
from app.modules.notifications.models import (
    EnterpriseEventOutbox,
    Notification,
    NotificationDelivery,
    WebPushSubscription,
)
from app.modules.notifications.router import (
    _cookie_origin_allowed,
    _websocket_credentials,
    notifications_ws,
)
from app.modules.notifications.service import (
    NotificationDeliveryError,
    NotificationDispatcher,
)
from app.modules.notifications.tasks import (
    drain_enterprise_event_outbox,
    drain_notification_deliveries,
    finalize_enterprise_event_outbox,
)
from app.modules.sender.models import EmailMessage
from app.modules.sender.schemas import SendEmailRequest
from app.modules.sender.service import SenderService
from app.modules.ses.service import SESWebhookHandler
from app.modules.tracking.service import TrackingService
from app.modules.users.models import User
from app.modules.webhooks.models import Webhook, WebhookDelivery, WebhookOutbox
from app.modules.webhooks.schemas import WebhookCreate
from app.modules.webhooks.service import (
    PinnedNetworkBackend,
    UnsafeWebhookURLError,
    WebhookDispatcher,
    WebhookService,
    validate_resolved_target,
)
from app.modules.webhooks.tasks import deliver_webhook


class Rows:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


def async_session_mock() -> Mock:
    db = Mock(spec=AsyncSession)
    db.flush = AsyncMock()
    db.scalar = AsyncMock()
    db.scalars = AsyncMock(return_value=Rows([]))
    db.get = AsyncMock()
    db.execute = AsyncMock()
    db.rollback = AsyncMock()
    return db


class SecretObject:
    def __init__(self) -> None:
        self.name = "visible"
        self.access_token = "access-value"
        self.nested = {"stripe_secret_key": "stripe-value", "SMTP-PASSWORD": "smtp-value"}


def test_structural_redaction_handles_objects_tuples_and_nested_names() -> None:
    result = sanitize(
        (
            SecretObject(),
            {"credentials": {"private_key": "private-value"}},
            {"ordinary": "visible", "database_url": "postgresql://user:password@db/app"},
        )
    )
    encoded = json.dumps(result)
    for secret in (
        "access-value",
        "stripe-value",
        "smtp-value",
        "private-value",
        "postgresql://user:password@db/app",
    ):
        assert secret not in encoded
    assert "visible" in encoded


@pytest.mark.asyncio
async def test_webhook_create_audit_never_contains_plaintext_secret() -> None:
    db = async_session_mock()
    settings = Settings(_env_file=None, app_secret_key="app-key")
    service = WebhookService(db, uuid4(), settings)  # type: ignore[arg-type]

    class Repo:
        async def add(self, row: Webhook) -> Webhook:
            row.id = uuid4()
            row.created_at = row.updated_at = datetime.now(UTC)
            return row

    service.repo = Repo()  # type: ignore[assignment]
    context = AuditContext(workspace_id=service.workspace_id, user_id=uuid4())
    token = set_audit_context(context)
    try:
        webhook, plain_secret = await service.create(
            WebhookCreate(
                name="CRM", url="https://hooks.example.com/events", events=["contact.created"]
            )
        )
    finally:
        reset_audit_context(token)
    audit_rows = [
        call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], AuditLog)
    ]
    assert len(audit_rows) == 1
    assert audit_rows[0].resource_id == webhook.id
    assert audit_rows[0].new_values is None
    assert plain_secret not in json.dumps(sanitize(audit_rows[0]))


@pytest.mark.asyncio
async def test_event_bus_is_fail_closed_for_audit() -> None:
    redis = SimpleNamespace(publish=AsyncMock())
    optional = SimpleNamespace(handle_event=AsyncMock(side_effect=RuntimeError("optional")))
    audit = SimpleNamespace(
        compliance_critical=True,
        handle_event=AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    event = IntegrationEvent(workspace_id=uuid4(), kind="contact.created")
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await EventBus(redis, [optional, audit]).publish(event)  # type: ignore[arg-type]


def test_enterprise_event_registry_has_required_events_and_handlers() -> None:
    assert {
        "email.bounced",
        "email.complained",
        "billing.limit_warning",
        "email.failed",
        "meeting.booked",
    } <= ENTERPRISE_EVENT_TYPES
    assert ENTERPRISE_HANDLER_REGISTRY == ("notifications", "audit", "webhooks", "billing")


def test_phase4_celery_tasks_routes_and_schedules_are_registered() -> None:
    from app.modules.notifications import tasks as notification_tasks

    includes = set(celery_app.conf.include)
    assert {
        "app.modules.notifications.tasks",
        "app.modules.webhooks.tasks",
        "app.modules.billing.tasks",
    } <= includes
    assert celery_app.conf.task_routes["app.modules.webhooks.tasks.*"] == {"queue": "webhooks"}
    assert "drain-webhook-outbox" in celery_app.conf.beat_schedule
    assert "drain-enterprise-event-outbox" in celery_app.conf.beat_schedule
    assert "drain-notification-deliveries" in celery_app.conf.beat_schedule
    assert "finalize-enterprise-event-outbox" in celery_app.conf.beat_schedule
    assert "rollover-billing-periods" in celery_app.conf.beat_schedule
    assert "app.modules.notifications.tasks.send_notification" not in celery_app.tasks
    assert not hasattr(notification_tasks, "send_notification")
    assert not hasattr(NotificationDispatcher, "dispatch")


@pytest.mark.asyncio
async def test_dns_rebinding_public_to_private_is_rejected() -> None:
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])

    async def resolver(_host: str, _port: int) -> list[str]:
        return next(answers)

    with pytest.raises(UnsafeWebhookURLError):
        await validate_resolved_target("https://hooks.example.com", resolver=resolver)


class PeerStream(httpcore.AsyncNetworkStream):
    def __init__(self, peer: str) -> None:
        self.peer = peer
        self.closed = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:  # noqa: ASYNC109
        return b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:  # noqa: ASYNC109
        return None

    async def aclose(self) -> None:
        self.closed = True

    async def start_tls(
        self,
        ssl_context: object,
        server_hostname: str | None = None,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> httpcore.AsyncNetworkStream:
        return self

    def get_extra_info(self, info: str) -> object:
        return (self.peer, 443) if info == "server_addr" else None


class PeerBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, peer: str) -> None:
        self.stream = PeerStream(peer)
        self.connected_host: str | None = None

    async def connect_tcp(self, host: str, port: int, **kwargs: object) -> PeerStream:
        self.connected_host = host
        return self.stream

    async def connect_unix_socket(self, path: str, **kwargs: object) -> PeerStream:
        return self.stream

    async def sleep(self, seconds: float) -> None:
        return None


@pytest.mark.asyncio
async def test_pinned_backend_connects_ip_and_verifies_peer() -> None:
    backend = PeerBackend("93.184.216.34")
    pinned = PinnedNetworkBackend("hooks.example.com", "93.184.216.34", backend)
    assert await pinned.connect_tcp("hooks.example.com", 443) is backend.stream
    assert backend.connected_host == "93.184.216.34"
    with pytest.raises(httpcore.ConnectError):
        await pinned.connect_tcp("rebound.example.com", 443)
    mismatch = PeerBackend("127.0.0.1")
    with pytest.raises(httpcore.ConnectError):
        await PinnedNetworkBackend("hooks.example.com", "93.184.216.34", mismatch).connect_tcp(
            "hooks.example.com", 443
        )
    assert mismatch.stream.closed


def send_request(
    campaign_id: UUID | None = None, contact_id: UUID | None = None
) -> SendEmailRequest:
    return SendEmailRequest(
        to="lead@example.com",
        subject="Hello",
        html="<p>Hello</p>",
        text="Hello",
        sender_email="sender@example.com",
        sender_name="Sender",
        campaign_id=campaign_id,
        contact_id=contact_id,
    )


@pytest.mark.asyncio
async def test_sender_rejects_foreign_campaign_before_insert() -> None:
    workspace_id = uuid4()
    sender = SenderService.__new__(SenderService)
    sender.workspace_id = workspace_id
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    sender.repo = SimpleNamespace(db=db, add=AsyncMock())
    with pytest.raises(NotFoundError, match="Кампания"):
        await sender.send(send_request(campaign_id=uuid4()))
    sender.repo.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_sender_requires_workspace_contact_email_and_campaign_membership() -> None:
    workspace_id, campaign_id, contact_id = uuid4(), uuid4(), uuid4()
    campaign = Campaign(id=campaign_id, workspace_id=workspace_id)
    contact = Contact(id=contact_id, workspace_id=workspace_id, email="other@example.com")
    sender = SenderService.__new__(SenderService)
    sender.workspace_id = workspace_id
    sender.repo = SimpleNamespace(
        db=SimpleNamespace(scalar=AsyncMock(side_effect=[campaign, contact]))
    )
    with pytest.raises(NotFoundError, match="Контакт"):
        await sender._validate_scope(send_request(campaign_id, contact_id))
    contact.email = "lead@example.com"
    sender.repo.db.scalar = AsyncMock(side_effect=[campaign, contact, None])
    with pytest.raises(NotFoundError, match="не включён"):
        await sender._validate_scope(send_request(campaign_id, contact_id))
    sender.repo.db.scalar = AsyncMock(side_effect=[campaign, contact, uuid4()])
    assert await sender._validate_scope(send_request(campaign_id, contact_id)) == (
        campaign,
        contact,
    )


@pytest.mark.asyncio
async def test_linkedin_enrichment_reserves_contact_quota() -> None:
    profile = LinkedInProfile(
        id=uuid4(),
        workspace_id=uuid4(),
        linkedin_id="person",
        first_name="A",
        last_name="B",
        company_domain="example.com",
    )
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=Rows([profile])),
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        flush=AsyncMock(),
    )
    billing = SimpleNamespace(reserve_quota=AsyncMock(return_value=True))
    hunter = SimpleNamespace(
        find_confident_email=AsyncMock(return_value={"email": "lead@example.com", "confidence": 90})
    )
    service = LinkedInService(
        db, profile.workspace_id, hunter=hunter, billing=billing  # type: ignore[arg-type]
    )
    assert (await service.enrich_emails())["enriched"] == 1
    billing.reserve_quota.assert_awaited_once_with("create_contact")
    assert any(isinstance(call.args[0], Contact) for call in db.add.call_args_list)


@pytest.mark.asyncio
async def test_linkedin_lead_gen_reserves_quota_and_propagates_limit() -> None:
    workspace_id = uuid4()
    client = SimpleNamespace(
        get_lead_gen_forms=AsyncMock(return_value=[{"id": "form"}]),
        get_form_leads=AsyncMock(
            return_value=[{"answers": [{"questionId": "email", "value": "lead@example.com"}]}]
        ),
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), add=Mock())
    billing = SimpleNamespace(reserve_quota=AsyncMock(side_effect=LimitExceededError("quota")))
    service = LinkedInService(
        db, workspace_id, client=client, billing=billing  # type: ignore[arg-type]
    )
    with pytest.raises(LimitExceededError):
        await service.sync_lead_gen_forms("account")
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_dispatch_writes_outbox_without_celery_publish() -> None:
    webhook = Webhook(
        id=uuid4(),
        workspace_id=uuid4(),
        name="CRM",
        url="https://example.com",
        events=["email.sent"],
        secret="x",
    )

    class DB:
        def __init__(self) -> None:
            self.added: list[object] = []

        async def scalar(self, _query: object) -> None:
            return None

        def add(self, row: object) -> None:
            self.added.append(row)
            if isinstance(row, WebhookDelivery):
                row.id = uuid4()

        async def flush(self) -> None:
            return None

    db = DB()
    dispatcher = WebhookDispatcher(db, webhook.workspace_id)  # type: ignore[arg-type]
    dispatcher.repo = SimpleNamespace(get_by_event=AsyncMock(return_value=[webhook]))
    rows = await dispatcher.dispatch("email.sent", {"message_id": "1"})
    assert len(rows) == 1
    assert any(isinstance(row, WebhookOutbox) for row in db.added)


def test_missing_webhook_delivery_is_retried_as_commit_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingDB:
        async def __aenter__(self) -> MissingDB:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, _model: object, _identifier: object) -> None:
            return None

    monkeypatch.setattr("app.database.async_session_factory", lambda: MissingDB())
    retry = Mock(side_effect=Retry())
    monkeypatch.setattr(deliver_webhook, "retry", retry)
    with pytest.raises(Retry):
        deliver_webhook.run(str(uuid4()))
    retry.assert_called_once()


def test_websocket_auth_has_no_query_token_and_supports_secure_carriers() -> None:
    assert "token" not in inspect.signature(notifications_ws).parameters
    header_ws = SimpleNamespace(
        headers={"authorization": "Bearer jwt.header.signature"}, cookies={}
    )
    assert _websocket_credentials(header_ws) == (
        "jwt.header.signature",
        None,
        "authorization",
    )
    cookie_ws = SimpleNamespace(
        headers={"origin": "http://localhost:5173"}, cookies={"access_token": "cookie.jwt"}
    )
    assert _websocket_credentials(cookie_ws) == ("cookie.jwt", None, "cookie")
    assert _cookie_origin_allowed(cookie_ws)
    assert not _cookie_origin_allowed(
        SimpleNamespace(headers={"origin": "https://evil.example"}, cookies={})
    )
    assert not _cookie_origin_allowed(SimpleNamespace(headers={}, cookies={}))
    protocol_ws = SimpleNamespace(
        headers={"sec-websocket-protocol": "bearer, jwt.header.signature"}, cookies={}
    )
    assert _websocket_credentials(protocol_ws) == (
        "jwt.header.signature",
        "bearer",
        "subprotocol",
    )
    reflected_jwt = SimpleNamespace(
        headers={"sec-websocket-protocol": "access_token.jwt.header.signature"}, cookies={}
    )
    assert _websocket_credentials(reflected_jwt) == (None, None, None)


@pytest.mark.asyncio
async def test_cookie_websocket_rejects_missing_or_foreign_origin() -> None:
    for origin in (None, "https://evil.example"):
        headers = {} if origin is None else {"origin": origin}
        websocket = SimpleNamespace(
            headers=headers,
            cookies={"access_token": "cookie.jwt"},
            close=AsyncMock(),
        )
        await notifications_ws(websocket, uuid4())  # type: ignore[arg-type]
        websocket.close.assert_awaited_once_with(code=1008)


def test_openapi_has_only_signed_ses_ingress_and_idempotency_header() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    schema = TestClient(create_app()).get("/openapi.json").json()
    assert "/api/v1/webhooks/ses" not in schema["paths"]
    assert "/api/v1/ses/webhook" in schema["paths"]
    parameters = schema["paths"]["/api/v1/billing/subscribe"]["post"]["parameters"]
    assert any(item["name"] == "Idempotency-Key" and item["in"] == "header" for item in parameters)


def test_stripe_checkout_uses_recurring_subscription_mode() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout"})

    async def run() -> None:
        settings = Settings(_env_file=None, stripe_secret_key="sk_test")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await StripeProvider(settings, client).create_payment(
                Decimal("9900"),
                "RUB",
                "Pro",
                "https://app.example/return",
                "checkout-request-1",
            )

    asyncio.run(run())
    assert "mode=subscription" in str(captured["body"])
    assert "recurring%5D%5Binterval%5D=month" in str(captured["body"])


@pytest.mark.asyncio
async def test_paid_period_and_invoice_application_require_confirmed_payment() -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    start, end = BillingService.paid_period(now)
    assert start == now
    assert end == datetime(2026, 2, 28, tzinfo=UTC)
    workspace_id = uuid4()
    subscription = Subscription(
        id=uuid4(),
        workspace_id=workspace_id,
        plan="free",
        status="active",
        current_period_start=now,
        current_period_end=now,
    )
    invoice = Invoice(
        id=uuid4(),
        workspace_id=workspace_id,
        subscription_id=subscription.id,
        provider="yookassa",
        plan="pro",
        kind="initial",
        amount=Decimal("9900"),
        currency="RUB",
        status="draft",
    )
    db = SimpleNamespace(get=AsyncMock(return_value=subscription))
    service = BillingService.__new__(BillingService)
    service.db = db
    service.workspace_id = workspace_id
    await service.apply_paid_invoice(invoice, period=(start, end))  # type: ignore[arg-type]
    assert invoice.status == "paid"
    assert subscription.current_period_end == end
    assert subscription.auto_renew is False


@pytest.mark.asyncio
async def test_payment_event_is_idempotent() -> None:
    service = BillingService.__new__(BillingService)
    service.db = SimpleNamespace(scalar=AsyncMock(return_value=PaymentEvent()))
    assert not await service.process_payment_event("stripe", "evt_1", {}, "cs_1")


def test_audit_migration_contains_immutable_trigger() -> None:
    from tests.test_alembic_offline import _offline_sql

    sql = _offline_sql()
    assert "CREATE TRIGGER trg_audit_logs_immutable" in sql
    assert "BEFORE UPDATE OR DELETE ON audit_logs" in sql
    assert "prevent_audit_log_mutation" in sql


@pytest.mark.asyncio
async def test_quota_reservation_uses_transaction_advisory_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProductionDB:
        def __init__(self) -> None:
            self.execute = AsyncMock()

    db = ProductionDB()
    service = BillingService.__new__(BillingService)
    service.db = db
    service.workspace_id = uuid4()
    monkeypatch.setattr("app.modules.billing.service.AsyncSession", ProductionDB)
    await service._lock_workspace_quota()
    db.execute.assert_awaited_once()
    compiled = str(db.execute.await_args.args[0])
    assert "pg_advisory_xact_lock" in compiled


@pytest.mark.asyncio
async def test_manual_payment_renews_only_after_confirmation_and_extends_term() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    subscription = Subscription(
        id=uuid4(),
        workspace_id=workspace_id,
        plan="pro",
        status="active",
        provider="yookassa",
        auto_renew=False,
        current_period_start=now,
        current_period_end=now + timedelta(days=10),
    )
    invoice = Invoice(
        id=uuid4(),
        workspace_id=workspace_id,
        subscription_id=subscription.id,
        provider="yookassa",
        provider_payment_id="pay_renewal",
        plan="pro",
        kind="renewal",
        amount=Decimal("9900"),
        currency="RUB",
        status="draft",
    )
    service = BillingService.__new__(BillingService)
    service.db = SimpleNamespace(get=AsyncMock(return_value=subscription))
    service.workspace_id = workspace_id
    original_end = subscription.current_period_end
    assert invoice.status == "draft" and subscription.current_period_end == original_end
    await service.apply_paid_invoice(invoice)
    assert invoice.status == "paid"
    assert invoice.period_start == original_end
    assert subscription.current_period_end > original_end
    assert subscription.auto_renew is False


def test_rollover_never_extends_unpaid_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    expired = datetime.now(UTC) - timedelta(days=1)
    paid = Subscription(
        workspace_id=uuid4(),
        plan="pro",
        status="active",
        provider="stripe",
        auto_renew=True,
        current_period_start=expired - timedelta(days=30),
        current_period_end=expired,
    )
    free = Subscription(
        workspace_id=uuid4(),
        plan="free",
        status="active",
        auto_renew=False,
        current_period_start=expired - timedelta(days=30),
        current_period_end=expired,
    )
    old_paid_end = paid.current_period_end

    class DB:
        commit = AsyncMock()

        async def __aenter__(self) -> DB:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def scalars(self, _query: object) -> Rows:
            return Rows([paid, free])

    monkeypatch.setattr("app.database.async_session_factory", lambda: DB())
    assert rollover_billing_periods.run() == {"subscriptions_updated": 2}
    assert paid.status == "past_due" and paid.current_period_end == old_paid_end
    assert free.status == "active" and free.current_period_end > datetime.now(UTC)


@pytest.mark.asyncio
async def test_ses_and_meeting_paths_emit_registered_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, campaign_id, contact_id = uuid4(), uuid4(), uuid4()
    message = EmailMessage(
        id=uuid4(),
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        contact_id=contact_id,
        recipient_email="lead@example.com",
        subject="Subject",
    )
    campaign = Campaign(id=campaign_id, workspace_id=workspace_id, bounced_count=0, meeting_count=0)
    contact = Contact(
        id=contact_id,
        workspace_id=workspace_id,
        email="lead@example.com",
        status="new",
        is_unsubscribed=False,
    )
    published = AsyncMock()
    monkeypatch.setattr("app.modules.ses.service.publish_enterprise_event", published)
    ses = SESWebhookHandler.__new__(SESWebhookHandler)
    ses.db = SimpleNamespace(get=AsyncMock(side_effect=[campaign, contact, contact]))
    ses._message = AsyncMock(side_effect=[message, message])
    await ses._handle_bounce(
        {"bounce": {"bounceType": "Permanent", "timestamp": "2026-09-07T10:00:00Z"}}
    )
    await ses._handle_complaint({"complaint": {"timestamp": "2026-09-07T10:01:00Z"}})
    assert [call.args[1].event_type for call in published.await_args_list] == [
        "email.bounced",
        "email.complained",
    ]

    meeting_publish = AsyncMock()
    monkeypatch.setattr("app.modules.tracking.service.publish_enterprise_event", meeting_publish)
    tracking = TrackingService.__new__(TrackingService)
    tracking.db = SimpleNamespace(scalar=AsyncMock(side_effect=[contact, campaign]))
    await tracking.record_meeting(workspace_id, contact_id, campaign_id)
    assert meeting_publish.await_args.args[1].event_type == "meeting.booked"


@pytest.mark.asyncio
async def test_sender_failure_emits_email_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_id = uuid4()
    sender = SenderService.__new__(SenderService)
    sender.workspace_id = workspace_id
    sender.settings = Settings(_env_file=None, smtp_host="smtp.example.com")
    sender.billing = SimpleNamespace(check_limits=AsyncMock(return_value=True))
    sender._validate_scope = AsyncMock(return_value=(None, None))
    sender._check_domain_rate = AsyncMock()
    sender._ensure_bitrix_lead = AsyncMock()
    row = EmailMessage(
        id=uuid4(),
        workspace_id=workspace_id,
        recipient_email="lead@example.com",
        subject="Subject",
    )
    sender.repo = SimpleNamespace(add=AsyncMock(return_value=row), db=object())
    monkeypatch.setattr(
        "app.modules.sender.service.aiosmtplib.send",
        AsyncMock(side_effect=OSError("smtp unavailable")),
    )
    published = AsyncMock()
    monkeypatch.setattr("app.core.events.publish_enterprise_event", published)
    with pytest.raises(OSError, match="smtp unavailable"):
        await sender.send(send_request())
    assert row.status == "failed"
    assert published.await_args.args[1].event_type == "email.failed"


@pytest.mark.asyncio
async def test_auth_login_logout_mfa_are_audited_and_audit_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(
        id=uuid4(),
        email="owner@example.com",
        password_hash="hash",
        full_name="Owner",
        failed_login_attempts=0,
        mfa_enabled=False,
    )
    auth = AuthService.__new__(AuthService)
    auth.db = SimpleNamespace(flush=AsyncMock())
    auth.users = SimpleNamespace(get_by_email=AsyncMock(return_value=user))
    session = AuthSession(id=uuid4(), user_id=user.id, family_id=uuid4())
    auth.sessions = SimpleNamespace(
        get_by_hash=AsyncMock(return_value=session), revoke_family=AsyncMock()
    )
    auth._issue_pair = AsyncMock(return_value=TokenPair(access_token="a", refresh_token="r"))
    auth.audit_user_action = AsyncMock()
    monkeypatch.setattr("app.modules.auth.service.verify_password", lambda *_: True)
    await auth.login(LoginRequest(email=user.email, password="correct-password"), "127.0.0.1", "ua")
    await auth.logout("refresh", "127.0.0.1", "ua")
    secret, _ = auth.setup_mfa(user)
    import pyotp

    await auth.verify_mfa(user, pyotp.TOTP(secret).now(), "127.0.0.1", "ua")
    assert [call.args[1] for call in auth.audit_user_action.await_args_list] == [
        "auth.login",
        "auth.logout",
        "auth.mfa_enabled",
    ]

    class ProductionDB:
        def __init__(self) -> None:
            self.scalars = AsyncMock(return_value=Rows([SimpleNamespace(workspace_id=uuid4())]))

    production_auth = AuthService.__new__(AuthService)
    production_auth.db = ProductionDB()
    monkeypatch.setattr("app.modules.auth.service.AsyncSession", ProductionDB)
    monkeypatch.setattr(
        "app.modules.auth.service.AuditService.log",
        AsyncMock(side_effect=RuntimeError("audit storage unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit storage unavailable"):
        await production_auth.audit_user_action(user.id, "auth.login")


def stripe_subscription() -> Subscription:
    now = datetime.now(UTC)
    return Subscription(
        id=uuid4(),
        workspace_id=uuid4(),
        plan="pro",
        status="active",
        provider="stripe",
        provider_subscription_id="sub_active",
        auto_renew=True,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )


def subscription_service(subscription: Subscription) -> BillingService:
    service = BillingService.__new__(BillingService)
    service.workspace_id = subscription.workspace_id
    service.settings = Settings(
        _env_file=None,
        stripe_secret_key="sk_test",
        yookassa_shop_id="shop",
        yookassa_secret_key="secret",
    )
    service.db = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        add=Mock(),
        flush=AsyncMock(),
        rollback=AsyncMock(),
    )
    service.repo = SimpleNamespace(subscription=AsyncMock(return_value=subscription))
    service._lock_workspace_quota = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_stripe_downgrade_cancels_before_clearing_provider_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription = stripe_subscription()
    service = subscription_service(subscription)
    observed_ids: list[str | None] = []

    async def cancel(
        _provider: object, subscription_id: str, *, immediately: bool
    ) -> dict[str, object]:
        observed_ids.append(subscription.provider_subscription_id)
        assert subscription_id == "sub_active" and immediately
        return {"status": "canceled"}

    monkeypatch.setattr(StripeProvider, "cancel_subscription", cancel)
    assert (
        await service.subscribe(SubscribeRequest(plan="free", idempotency_key="downgrade-request"))
        is None
    )
    assert observed_ids == ["sub_active"]
    assert subscription.plan == "free"
    assert subscription.provider is None and subscription.provider_subscription_id is None


@pytest.mark.asyncio
async def test_stripe_switch_is_fail_safe_and_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    subscription = stripe_subscription()
    service = subscription_service(subscription)
    create = AsyncMock()
    monkeypatch.setattr(YooKassaProvider, "create_payment", create)
    cancel_error = AsyncMock(side_effect=RuntimeError("stripe unavailable"))
    monkeypatch.setattr(StripeProvider, "cancel_subscription", cancel_error)
    with pytest.raises(RuntimeError, match="stripe unavailable"):
        await service.subscribe(
            SubscribeRequest(plan="business", provider="yookassa", idempotency_key="switch-request")
        )
    assert subscription.provider_subscription_id == "sub_active"
    assert subscription.plan == "pro" and subscription.auto_renew
    create.assert_not_awaited()

    order: list[str] = []

    async def cancel_ok(*_args: object, **_kwargs: object) -> dict[str, object]:
        order.append("cancel")
        return {"status": "canceled"}

    async def create_ok(*_args: object, **_kwargs: object) -> SimpleNamespace:
        order.append("checkout")
        return SimpleNamespace(payment_id="pay_1", url="https://checkout")

    monkeypatch.setattr(StripeProvider, "cancel_subscription", cancel_ok)
    monkeypatch.setattr(YooKassaProvider, "create_payment", create_ok)
    invoice = await service.subscribe(
        SubscribeRequest(plan="business", provider="yookassa", idempotency_key="switch-request")
    )
    assert order == ["cancel", "checkout"]
    assert invoice and invoice.idempotency_key == "switch-request"
    assert subscription.provider_subscription_id == "sub_active"
    assert not subscription.auto_renew

    service.db.scalar.return_value = invoice
    order.clear()
    assert (
        await service.subscribe(
            SubscribeRequest(plan="business", provider="yookassa", idempotency_key="switch-request")
        )
        is invoice
    )
    assert order == []
    with pytest.raises(AppError, match="другого платежа"):
        await service.subscribe(
            SubscribeRequest(plan="pro", provider="stripe", idempotency_key="switch-request")
        )


@pytest.mark.asyncio
async def test_regular_stripe_cancel_is_confirmed_before_local_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription = stripe_subscription()
    service = subscription_service(subscription)
    service.get_or_create_subscription = AsyncMock(return_value=subscription)
    failure = AsyncMock(side_effect=AppError("not confirmed"))
    monkeypatch.setattr(StripeProvider, "cancel_subscription", failure)
    with pytest.raises(AppError, match="not confirmed"):
        await service.cancel()
    assert subscription.auto_renew and subscription.cancel_at is None
    success = AsyncMock(return_value={"cancel_at_period_end": True})
    monkeypatch.setattr(StripeProvider, "cancel_subscription", success)
    await service.cancel()
    success.assert_awaited_once_with("sub_active", immediately=False)
    assert not subscription.auto_renew
    assert subscription.provider_subscription_id == "sub_active"


@pytest.mark.asyncio
async def test_provider_idempotency_key_is_forwarded_exactly() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "yookassa" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "id": "pay_1",
                    "status": "pending",
                    "confirmation": {"confirmation_url": "https://pay"},
                },
            )
        if "stripe" in request.url.host:
            return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout"})
        return httpx.Response(
            200,
            json={"Success": True, "PaymentId": "tk_1", "PaymentURL": "https://tinkoff"},
        )

    settings = Settings(
        _env_file=None,
        yookassa_shop_id="shop",
        yookassa_secret_key="secret",
        stripe_secret_key="sk_test",
        tinkoff_terminal_key="terminal",
        tinkoff_password="password",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await YooKassaProvider(settings, client).create_payment(
            Decimal("1"), "RUB", "D", "https://return", "stable-request-key"
        )
        await StripeProvider(settings, client).create_payment(
            Decimal("1"), "RUB", "D", "https://return", "stable-request-key"
        )
        await TinkoffProvider(settings, client).create_payment(
            Decimal("1"), "RUB", "D", "https://return", "stable-request-key"
        )
    assert requests[0].headers["Idempotence-Key"] == "stable-request-key"
    assert requests[1].headers["Idempotency-Key"] == "stable-request-key"
    assert json.loads(requests[2].content)["OrderId"] == "stable-request-key"


@pytest.mark.asyncio
async def test_provider_idempotency_is_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = stripe_subscription()
    second = stripe_subscription()
    first.provider = second.provider = None
    first.provider_subscription_id = second.provider_subscription_id = None
    first.auto_renew = second.auto_renew = False
    services = [subscription_service(first), subscription_service(second)]
    captured: list[str] = []

    async def create_payment(*args: object) -> SimpleNamespace:
        captured.append(str(args[-1]))
        return SimpleNamespace(payment_id=f"pay_{len(captured)}", url="https://checkout")

    monkeypatch.setattr(YooKassaProvider, "create_payment", create_payment)
    for service in services:
        await service.subscribe(
            SubscribeRequest(
                plan="business", provider="yookassa", idempotency_key="same-client-key"
            )
        )
    assert captured[0] != captured[1]
    assert all(key.startswith("pbm_") and len(key) == 36 for key in captured)
    assert "same-client-key" not in captured


def test_provider_callback_identities_are_unambiguous_and_provider_scoped() -> None:
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in Invoice.__table__.constraints
        if constraint.name
    }
    assert constraints["uq_invoices_provider_payment_identity"] == (
        "provider",
        "provider_payment_id",
    )
    assert constraints["uq_invoices_provider_invoice_identity"] == (
        "provider",
        "provider_invoice_id",
    )


@pytest.mark.asyncio
async def test_provider_identity_collision_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription = stripe_subscription()
    subscription.provider = None
    subscription.provider_subscription_id = None
    subscription.auto_renew = False
    service = subscription_service(subscription)
    service.db.flush.side_effect = IntegrityError("insert", {}, RuntimeError("duplicate"))
    checkout = AsyncMock(return_value=SimpleNamespace(payment_id="shared", url="https://pay"))
    monkeypatch.setattr(YooKassaProvider, "create_payment", checkout)
    with pytest.raises(AppError, match="уже используемый"):
        await service.subscribe(
            SubscribeRequest(plan="pro", provider="yookassa", idempotency_key="collision-request")
        )
    service.db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_payment_callback_cannot_activate_cross_tenant_invoice() -> None:
    owner_workspace = uuid4()
    foreign_workspace = uuid4()
    subscription = Subscription(
        id=uuid4(),
        workspace_id=foreign_workspace,
        plan="free",
        status="active",
        current_period_start=datetime.now(UTC),
        current_period_end=datetime.now(UTC) + timedelta(days=30),
    )
    invoice = Invoice(
        id=uuid4(),
        workspace_id=foreign_workspace,
        subscription_id=subscription.id,
        provider="yookassa",
        provider_payment_id="pay_foreign",
        plan="pro",
        amount=Decimal("9900"),
        currency="RUB",
        status="draft",
    )
    service = BillingService.__new__(BillingService)
    service.workspace_id = owner_workspace
    service.settings = Settings(_env_file=None)
    service.db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[None, invoice]),
        get=AsyncMock(return_value=subscription),
        add=Mock(),
        flush=AsyncMock(),
    )
    with pytest.raises(AppError, match="workspace"):
        await service.process_payment_event("yookassa", "evt_foreign", {}, "pay_foreign")
    assert invoice.status == "draft"


@pytest.mark.asyncio
async def test_stripe_cancellation_requires_provider_confirmation() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "sub_1", "status": "canceled"})
        return httpx.Response(200, json={"id": "sub_1", "cancel_at_period_end": False})

    settings = Settings(_env_file=None, stripe_secret_key="sk_test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await StripeProvider(settings, client).cancel_subscription(
            "sub_1", immediately=True
        )
        assert result["status"] == "canceled"
        with pytest.raises(PaymentProviderError, match="не подтвердил"):
            await StripeProvider(settings, client).cancel_subscription("sub_1")
    assert requests[0].method == "DELETE"
    assert requests[0].headers["Idempotency-Key"] == "cancel:sub_1:immediate"


class EventSession(AsyncSession):
    def __init__(self) -> None:
        super().__init__()
        self.added: list[object] = []

    def add(self, instance: object, *, _warn: bool = True) -> None:
        self.added.append(instance)

    async def flush(self, objects: object = None) -> None:
        return None


@pytest.mark.asyncio
async def test_enterprise_outbox_is_audit_first_and_has_no_precommit_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = EventSession()
    audit = AsyncMock(side_effect=RuntimeError("audit failed"))
    billing = AsyncMock()
    notification = AsyncMock()
    webhook = AsyncMock()
    monkeypatch.setattr(AuditService, "log_event", audit)
    monkeypatch.setattr(BillingService, "update_usage", billing)
    monkeypatch.setattr(NotificationDispatcher, "handle_event", notification)
    monkeypatch.setattr(WebhookDispatcher, "handle_event", webhook)
    event = IntegrationEvent(workspace_id=uuid4(), kind="email.failed")
    with pytest.raises(RuntimeError, match="audit failed"):
        await publish_enterprise_event(db, event)
    assert db.added == []
    billing.assert_not_awaited()
    notification.assert_not_awaited()
    webhook.assert_not_awaited()

    audit.side_effect = None
    await publish_enterprise_event(db, event)
    audit.assert_awaited()
    billing.assert_awaited_once()
    assert len(db.added) == 1 and isinstance(db.added[0], EnterpriseEventOutbox)
    notification.assert_not_awaited()
    webhook.assert_not_awaited()
    await db.close()


def test_enterprise_outbox_worker_dispatches_only_committed_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = EnterpriseEventOutbox(
        id=uuid4(),
        workspace_id=uuid4(),
        event_id=uuid4(),
        event_type="email.failed",
        data={"message": "failed"},
        occurred_at=datetime.now(UTC),
        attempts=0,
    )

    class DB:
        commit = AsyncMock()

        async def __aenter__(self) -> DB:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def scalar(self, _query: object) -> EnterpriseEventOutbox:
            return row

    redis = SimpleNamespace(publish=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr("app.database.async_session_factory", lambda: DB())
    monkeypatch.setattr("redis.asyncio.Redis.from_url", lambda *_args, **_kwargs: redis)
    notification = AsyncMock(return_value=[])
    realtime = AsyncMock()
    webhook = AsyncMock()
    monkeypatch.setattr(NotificationDispatcher, "enqueue_event", notification)
    monkeypatch.setattr(NotificationDispatcher, "publish_realtime", realtime)
    monkeypatch.setattr(WebhookDispatcher, "handle_event", webhook)
    assert drain_enterprise_event_outbox.run(limit=1) == {"materialized": 1}
    webhook.assert_awaited_once()
    notification.assert_awaited_once()
    realtime.assert_awaited_once_with([])
    assert row.materialized_at is not None and row.dispatched_at is None and row.attempts == 1


def test_enterprise_event_not_completed_while_any_durable_channel_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = EnterpriseEventOutbox(
        id=uuid4(),
        workspace_id=uuid4(),
        event_id=uuid4(),
        event_type="email.failed",
        data={},
        occurred_at=datetime.now(UTC),
        materialized_at=datetime.now(UTC),
        dispatched_at=None,
    )

    class DB:
        def __init__(self, counts: list[int]) -> None:
            self.counts = counts
            self.commit = AsyncMock()

        async def __aenter__(self) -> DB:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def scalars(self, _query: object) -> Rows:
            return Rows([row])

        async def scalar(self, _query: object) -> int:
            return self.counts.pop(0)

    sessions = iter([DB([1, 0]), DB([0, 0])])
    monkeypatch.setattr("app.database.async_session_factory", lambda: next(sessions))
    assert finalize_enterprise_event_outbox.run(limit=1) == {"completed": 0}
    assert row.dispatched_at is None
    assert finalize_enterprise_event_outbox.run(limit=1) == {"completed": 1}
    assert row.dispatched_at is not None


@pytest.mark.asyncio
async def test_notification_event_materializes_idempotent_per_channel_jobs() -> None:
    workspace_id = uuid4()
    user_id = uuid4()
    event = IntegrationEvent(
        workspace_id=workspace_id,
        event_id=uuid4(),
        kind="email.failed",
        data={"message": "failed"},
    )
    notification = Notification(
        id=uuid4(),
        user_id=user_id,
        workspace_id=workspace_id,
        event_id=event.event_id,
        type="error",
        title="Ошибка отправки",
        message="failed",
        data={"event_id": str(event.event_id)},
        is_read=False,
    )
    preference = SimpleNamespace(
        email_notifications={},
        webpush_notifications={"error": True},
        telegram_notifications={"error": True},
        telegram_chat_id="42",
    )
    push = WebPushSubscription(
        id=uuid4(),
        user_id=user_id,
        endpoint="https://push.example/subscription",
        p256dh="key",
        auth="auth",
        is_active=True,
    )
    added: list[object] = []
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=Rows([SimpleNamespace(user_id=user_id)])),
        scalar=AsyncMock(side_effect=[None, None, None, None]),
        add=lambda row: added.append(row),
        flush=AsyncMock(),
    )
    dispatcher = NotificationDispatcher(db, settings=Settings(_env_file=None))  # type: ignore[arg-type]
    dispatcher.repo = SimpleNamespace(
        create=AsyncMock(return_value=notification),
        preference=AsyncMock(return_value=preference),
        subscriptions=AsyncMock(return_value=[push]),
    )

    assert await dispatcher.enqueue_event(event) == [notification]
    deliveries = [row for row in added if isinstance(row, NotificationDelivery)]
    assert {(row.channel, row.target_id) for row in deliveries} == {
        ("email", ""),
        ("webpush", str(push.id)),
        ("telegram", ""),
    }

    added.clear()
    db.scalar.side_effect = [notification, *deliveries]
    assert await dispatcher.enqueue_event(event) == [notification]
    assert added == []


@pytest.mark.asyncio
async def test_notification_channel_partial_failure_retries_only_failed_with_stable_id() -> None:
    notification = Notification(
        id=uuid4(),
        user_id=uuid4(),
        workspace_id=uuid4(),
        event_id=uuid4(),
        type="error",
        title="Failure",
        message="Delivery test",
        data={},
        is_read=False,
    )
    email = NotificationDelivery(
        id=uuid4(),
        notification_id=notification.id,
        channel="email",
        target_id="",
        status="pending",
        attempts=0,
    )
    push_subscription = WebPushSubscription(
        id=uuid4(),
        user_id=notification.user_id,
        endpoint="https://push.example/subscription",
        p256dh="key",
        auth="auth",
        is_active=True,
    )
    push = NotificationDelivery(
        id=uuid4(),
        notification_id=notification.id,
        channel="webpush",
        target_id=str(push_subscription.id),
        status="pending",
        attempts=0,
    )

    class DB:
        current = email
        flush = AsyncMock()

        async def scalar(self, _query: object) -> NotificationDelivery:
            return self.current

        async def get(self, model: object, _identifier: object) -> object:
            if model is Notification:
                return notification
            if model is WebPushSubscription:
                return push_subscription
            return None

    payloads: list[dict[str, object]] = []

    class Push:
        async def send(
            self, _subscription: WebPushSubscription, payload: dict[str, object]
        ) -> None:
            payloads.append(payload)
            if len(payloads) == 1:
                raise RuntimeError("push unavailable")

    db = DB()
    dispatcher = NotificationDispatcher(db, settings=Settings(_env_file=None), push_sender=Push())  # type: ignore[arg-type]
    dispatcher._send_email = AsyncMock()  # type: ignore[method-assign]

    await dispatcher.deliver_channel(email.id)
    await dispatcher.deliver_channel(email.id)
    dispatcher._send_email.assert_awaited_once_with(notification, email.id)
    assert email.status == "succeeded" and email.attempts == 1

    db.current = push
    with pytest.raises(NotificationDeliveryError, match="push unavailable"):
        await dispatcher.deliver_channel(push.id)
    assert push.status == "failed" and push.attempts == 1 and push.delivered_at is None
    await dispatcher.deliver_channel(push.id)
    assert push.status == "succeeded" and push.attempts == 2
    assert [payload["delivery_id"] for payload in payloads] == [str(push.id), str(push.id)]
    assert email.attempts == 1
    assert drain_notification_deliveries.name.endswith("drain_notification_deliveries")


@pytest.mark.asyncio
async def test_failed_auth_security_sink_is_durable_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    added: list[object] = []

    class DB:
        commit = AsyncMock()

        async def __aenter__(self) -> DB:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def add(self, row: object) -> None:
            added.append(row)

    monkeypatch.setattr("app.database.async_session_factory", lambda: DB())
    await SecurityAuditSink(Settings(_env_file=None, app_secret_key="audit-hmac-key")).record(
        "auth.failure",
        "bad_password",
        email="Owner@Example.com",
        user_id=uuid4(),
        ip_address="127.0.0.1",
        user_agent="tests",
        data={"access_token": "must-not-leak"},
    )
    event = added[0]
    assert isinstance(event, SecurityAuditEvent)
    assert event.email_hash and event.email_hash != "owner@example.com"
    assert event.data == {"access_token": "[REDACTED]"}


@pytest.mark.asyncio
async def test_failed_auth_paths_emit_safe_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        email="owner@example.com",
        password_hash="hash",
        full_name="Owner",
        failed_login_attempts=0,
        mfa_enabled=False,
    )
    db = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
    auth = AuthService.__new__(AuthService)
    auth.db = db
    auth.users = SimpleNamespace(get_by_email=AsyncMock(return_value=user))
    auth.sessions = SimpleNamespace(get_by_hash=AsyncMock(), revoke_family=AsyncMock())
    sink = SimpleNamespace(record=AsyncMock())
    auth.security_audit = sink

    monkeypatch.setattr("app.modules.auth.service.verify_password", lambda *_: False)
    with pytest.raises(AuthenticationError):
        await auth.login(
            LoginRequest(email=user.email, password="NeverLogThis1"), "127.0.0.1", "ua"
        )

    user.locked_until = now + timedelta(minutes=5)
    with pytest.raises(AuthenticationError):
        await auth.login(
            LoginRequest(email=user.email, password="NeverLogThis1"), "127.0.0.1", "ua"
        )
    user.locked_until = None

    import pyotp

    secret = pyotp.random_base32()
    user.mfa_enabled, user.mfa_secret = True, secret
    monkeypatch.setattr("app.modules.auth.service.verify_password", lambda *_: True)
    with pytest.raises(AuthenticationError):
        await auth.login(
            MFALoginRequest(email=user.email, password="NeverLogThis1", code="000000"),
            "127.0.0.1",
            "ua",
        )

    family_id, session_id = uuid4(), uuid4()
    refresh = create_refresh_token(user.id, session_id, family_id)
    auth.sessions.get_by_hash.return_value = None
    with pytest.raises(AuthenticationError):
        await auth.refresh(refresh)
    auth.sessions.get_by_hash.return_value = AuthSession(
        id=session_id,
        user_id=user.id,
        family_id=family_id,
        expires_at=now - timedelta(seconds=1),
    )
    with pytest.raises(AuthenticationError):
        await auth.refresh(refresh)
    reasons = [call.args[1] for call in sink.record.await_args_list]
    assert reasons == [
        "bad_password",
        "locked",
        "bad_mfa",
        "refresh_reuse",
        "refresh_expired",
    ]
    assert [call.args[0] for call in sink.record.await_args_list] == [
        "auth.login_failed",
        "auth.login_failed",
        "auth.mfa_failed",
        "auth.refresh_reuse",
        "auth.refresh_expired",
    ]
    serialized = json.dumps(
        [call.args + tuple(call.kwargs.items()) for call in sink.record.await_args_list],
        default=str,
    )
    assert "NeverLogThis1" not in serialized
    assert "000000" not in serialized
    assert refresh not in serialized


@pytest.mark.asyncio
async def test_standalone_mfa_failure_uses_durable_secret_free_sink() -> None:
    user = User(
        id=uuid4(),
        email="owner@example.com",
        password_hash="hash",
        full_name="Owner",
        mfa_secret=pyotp.random_base32(),
        mfa_enabled=False,
    )
    auth = AuthService.__new__(AuthService)
    auth.db = SimpleNamespace(flush=AsyncMock())
    auth.security_audit = SimpleNamespace(record=AsyncMock())
    with pytest.raises(AuthenticationError, match="2FA"):
        await auth.verify_mfa(user, "000000", "127.0.0.1", "tests")
    auth.security_audit.record.assert_awaited_once_with(
        "auth.mfa_failed",
        "bad_mfa",
        email=user.email,
        user_id=user.id,
        ip_address="127.0.0.1",
        user_agent="tests",
    )
    assert "000000" not in repr(auth.security_audit.record.await_args)


@pytest.mark.asyncio
async def test_refresh_decode_failures_are_durably_classified_without_token() -> None:
    auth = AuthService.__new__(AuthService)
    auth.db = SimpleNamespace()
    auth.security_audit = SimpleNamespace(record=AsyncMock())
    auth.sessions = SimpleNamespace()

    malformed = "definitely-not-a-jwt"
    with pytest.raises(AuthenticationError):
        await auth.refresh(malformed)

    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": str(uuid4()),
            "sid": str(uuid4()),
            "family": str(uuid4()),
            "type": "refresh",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        get_settings().app_secret_key,
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        await auth.refresh(expired)

    invalid = jwt.encode(
        {
            "sub": str(uuid4()),
            "sid": str(uuid4()),
            "family": str(uuid4()),
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        "a-different-signing-secret-long-enough",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        await auth.refresh(invalid)

    calls = auth.security_audit.record.await_args_list
    assert [(call.args[0], call.args[1]) for call in calls] == [
        ("auth.refresh_failed", "refresh_malformed"),
        ("auth.refresh_expired", "refresh_expired"),
        ("auth.refresh_failed", "refresh_invalid"),
    ]
    serialized = repr(calls)
    assert malformed not in serialized and expired not in serialized and invalid not in serialized
