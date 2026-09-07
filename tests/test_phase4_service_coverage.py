from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.core.events import IntegrationEvent
from app.core.exceptions import AppError, NotFoundError
from app.modules.audit.models import AuditExport, AuditLog
from app.modules.audit.service import AuditService
from app.modules.billing.models import Invoice, PaymentEvent, Subscription, UsageLog
from app.modules.billing.providers import (
    Checkout,
    PaymentProviderError,
    StripeProvider,
    TinkoffProvider,
    YooKassaProvider,
)
from app.modules.billing.schemas import SubscribeRequest
from app.modules.billing.service import BillingService, LimitExceededError
from app.modules.notifications.models import (
    Notification,
    NotificationPreference,
)
from app.modules.notifications.schemas import PreferenceUpdate, WebPushSubscriptionCreate
from app.modules.notifications.service import (
    NotificationDeliveryError,
    NotificationDispatcher,
    NotificationService,
)
from app.modules.users.models import User


class Values:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


def notification_row(kind: str = "campaign_started") -> Notification:
    row = Notification(
        id=uuid4(),
        user_id=uuid4(),
        workspace_id=uuid4(),
        type=kind,
        title="Title",
        message="Message",
        data={"value": 1},
        channel="email",
        is_read=False,
    )
    row.created_at = datetime.now(UTC)
    return row


def test_notification_serialization_and_channel_preferences() -> None:
    row = notification_row()
    preference = NotificationPreference(
        user_id=row.user_id,
        workspace_id=row.workspace_id,
        email_notifications={row.type: True},
        webpush_notifications={row.type: True},
        telegram_notifications={row.type: True},
        telegram_chat_id="1",
    )
    assert NotificationDispatcher._enabled(preference, "email", row.type)
    assert NotificationDispatcher._enabled(preference, "webpush", row.type)
    assert NotificationDispatcher._enabled(preference, "telegram", row.type)
    assert NotificationDispatcher.serialize(row)["created_at"] == row.created_at.isoformat()
    missing_date = notification_row()
    missing_date.created_at = None  # type: ignore[assignment]
    assert NotificationDispatcher.serialize(missing_date)["created_at"]


@pytest.mark.asyncio
async def test_notification_publish_send_email_and_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = notification_row("error")
    redis = SimpleNamespace(publish=AsyncMock(side_effect=ConnectionError("down")))
    db = SimpleNamespace(
        get=AsyncMock(return_value=User(id=row.user_id, email="user@example.com")),
        scalars=AsyncMock(return_value=Values([SimpleNamespace(user_id=row.user_id)])),
    )
    settings = Settings(
        _env_file=None,
        smtp_host="smtp.example.com",
        smtp_username="mailer",
        smtp_password="password",
    )
    dispatcher = NotificationDispatcher(db, redis=redis, settings=settings)  # type: ignore[arg-type]
    await dispatcher._publish(row.user_id, {"message": "hello"})
    smtp_send = AsyncMock()
    monkeypatch.setattr("app.modules.notifications.service.aiosmtplib.send", smtp_send)
    delivery_id = uuid4()
    await dispatcher._send_email(row, delivery_id)
    smtp_send.assert_awaited_once()
    message_id_domain = settings.notification_from_email.rsplit("@", 1)[-1]
    assert smtp_send.await_args.args[0]["Message-ID"] == (
        f"<notification-{delivery_id}@{message_id_domain}>"
    )
    db.get.return_value = None
    with pytest.raises(NotificationDeliveryError):
        await dispatcher._send_email(row, delivery_id)
    dispatcher.enqueue_event = AsyncMock(return_value=[])
    await dispatcher.handle_event(
        IntegrationEvent(
            workspace_id=row.workspace_id,
            kind="email.failed",
            data={"message": "custom"},
        )
    )
    dispatcher.enqueue_event.assert_awaited_once()
    assert (
        await NotificationDispatcher.enqueue_event(
            dispatcher, IntegrationEvent(workspace_id=row.workspace_id, kind="unknown")
        )
        == []
    )


@pytest.mark.asyncio
async def test_notification_telegram_and_user_service(monkeypatch: pytest.MonkeyPatch) -> None:
    row = notification_row()
    db = SimpleNamespace(flush=AsyncMock(), add=Mock(), scalar=AsyncMock())
    dispatcher = NotificationDispatcher.__new__(NotificationDispatcher)
    dispatcher.settings = Settings(_env_file=None, telegram_bot_token="bot-token")
    delivery_id = uuid4()
    with pytest.raises(NotificationDeliveryError):
        await dispatcher._send_telegram(row, None, delivery_id)
    preference = NotificationPreference(
        user_id=row.user_id,
        workspace_id=row.workspace_id,
        email_notifications={},
        webpush_notifications={},
        telegram_notifications={},
        telegram_chat_id="42",
    )
    response = httpx.Response(200, request=httpx.Request("POST", "https://api.telegram.org"))
    post = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    await dispatcher._send_telegram(row, preference, delivery_id)
    post.assert_awaited_once()
    assert post.await_args.kwargs["headers"] == {"X-PBM-Delivery-ID": str(delivery_id)}

    service = NotificationService(db, row.workspace_id, row.user_id)  # type: ignore[arg-type]
    service.repo = SimpleNamespace(
        get_for_user=AsyncMock(return_value=None), preference=AsyncMock(return_value=None)
    )
    with pytest.raises(NotFoundError):
        await service.mark_read(row.id)
    service.repo.get_for_user.return_value = row
    assert (await service.mark_read(row.id)).is_read
    updated = await service.update_preferences(
        PreferenceUpdate(email_notifications={"error": True}, telegram_chat_id="42")
    )
    assert updated.email_notifications == {"error": True}
    db.scalar.return_value = None
    created = await service.subscribe_webpush(
        WebPushSubscriptionCreate(endpoint="https://push.example/new", p256dh="p", auth="a")
    )
    assert created.user_id == row.user_id
    db.scalar.return_value = created
    refreshed = await service.subscribe_webpush(
        WebPushSubscriptionCreate(endpoint="https://push.example/new", p256dh="new", auth="new")
    )
    assert refreshed.p256dh == "new" and refreshed.is_active


@pytest.mark.asyncio
async def test_audit_log_event_and_both_export_formats() -> None:
    workspace_id, user_id = uuid4(), uuid4()
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    service = AuditService(db, workspace_id)  # type: ignore[arg-type]
    service.repo = SimpleNamespace(create=AsyncMock(side_effect=lambda row: row))
    event = IntegrationEvent(
        workspace_id=workspace_id,
        actor_id=user_id,
        resource_id=uuid4(),
        resource_type="contact",
        kind="contact.created",
        data={"access_token": "hidden", "name": "Visible"},
    )
    await service.handle_event(event)
    logged = service.repo.create.await_args.args[0]
    assert logged.new_values == {"access_token": "[REDACTED]", "name": "Visible"}
    row = AuditLog(
        workspace_id=workspace_id,
        user_id=user_id,
        action="contact.created",
        resource_type="contact",
        resource_id=event.resource_id,
        created_at=datetime.now(UTC),
    )
    csv_content, csv_type = await service.export([row], "csv", user_id)
    pdf_content, pdf_type = await service.export([row], "pdf", user_id)
    assert b"contact.created" in csv_content and csv_type.startswith("text/csv")
    assert pdf_content.startswith(b"%PDF") and pdf_type == "application/pdf"
    assert sum(isinstance(call.args[0], AuditExport) for call in db.add.call_args_list) == 2


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        yookassa_shop_id="shop",
        yookassa_secret_key="secret",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        tinkoff_terminal_key="terminal",
        tinkoff_password="password",
    )


@pytest.mark.asyncio
async def test_payment_provider_success_and_failure_branches() -> None:
    settings = configured_settings()

    async def success(request: httpx.Request) -> httpx.Response:
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
            if "/subscriptions/" in request.url.path:
                return httpx.Response(200, json={"cancel_at_period_end": True})
            return httpx.Response(200, json={"id": "cs_1", "url": "https://stripe"})
        return httpx.Response(
            200, json={"Success": True, "PaymentId": "tk_1", "PaymentURL": "https://tinkoff"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(success)) as client:
        assert (
            await YooKassaProvider(settings, client).create_payment(
                Decimal("1"), "RUB", "D", "https://return", "request-yookassa"
            )
        ).payment_id == "pay_1"
        assert (
            await StripeProvider(settings, client).create_payment(
                Decimal("1"), "RUB", "D", "https://return", "request-stripe"
            )
        ).payment_id == "cs_1"
        await StripeProvider(settings, client).cancel_subscription("sub_1")
        assert (
            await TinkoffProvider(settings, client).create_payment(
                Decimal("1"), "RUB", "D", "https://return", "request-tinkoff"
            )
        ).payment_id == "tk_1"

    empty = Settings(_env_file=None)
    for operation in (
        YooKassaProvider(empty).create_payment(
            Decimal("1"), "RUB", "D", "https://return", "request-yookassa"
        ),
        StripeProvider(empty).create_payment(
            Decimal("1"), "RUB", "D", "https://return", "request-stripe"
        ),
        StripeProvider(empty).cancel_subscription("sub"),
        TinkoffProvider(empty).create_payment(
            Decimal("1"), "RUB", "D", "https://return", "request-tinkoff"
        ),
    ):
        with pytest.raises(PaymentProviderError):
            await operation
    with pytest.raises(PaymentProviderError):
        await TinkoffProvider(settings).create_payment(
            Decimal("1"), "USD", "D", "https://return", "request-tinkoff"
        )

    async def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(rejected)) as client:
        with pytest.raises(PaymentProviderError):
            await YooKassaProvider(settings, client).create_payment(
                Decimal("1"), "RUB", "D", "https://return", "request-yookassa"
            )
        with pytest.raises(PaymentProviderError):
            await StripeProvider(settings, client).create_payment(
                Decimal("1"), "RUB", "D", "https://return", "request-stripe"
            )
        with pytest.raises(PaymentProviderError):
            await StripeProvider(settings, client).cancel_subscription("sub")

    async def declined(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json={"Success": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(declined)) as client:
        with pytest.raises(PaymentProviderError):
            await TinkoffProvider(settings, client).create_payment(
                Decimal("1"), "RUB", "D", "https://return", "request-tinkoff"
            )


def test_stripe_verifier_rejects_missing_malformed_stale_and_invalid_json() -> None:
    body = b"{}"
    with pytest.raises(PaymentProviderError):
        StripeProvider(Settings(_env_file=None)).verify_webhook(body, "")
    provider = StripeProvider(configured_settings())
    with pytest.raises(PaymentProviderError):
        provider.verify_webhook(body, "bad")
    with pytest.raises(PaymentProviderError):
        provider.verify_webhook(body, f"t={int(time.time()) - 10000},v1=x")
    timestamp = int(time.time())
    import hashlib
    import hmac

    signature = hmac.new(
        b"whsec_test", f"{timestamp}.".encode() + b"not-json", hashlib.sha256
    ).hexdigest()
    with pytest.raises(PaymentProviderError):
        provider.verify_webhook(b"not-json", f"t={timestamp},v1={signature}")


def make_subscription(plan: str = "free", status: str = "active") -> Subscription:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    return Subscription(
        id=uuid4(),
        workspace_id=uuid4(),
        plan=plan,
        status=status,
        current_period_start=start,
        current_period_end=start + timedelta(days=30),
        auto_renew=False,
    )


def billing_service(subscription: Subscription | None = None) -> BillingService:
    service = BillingService.__new__(BillingService)
    service.workspace_id = subscription.workspace_id if subscription else uuid4()
    service.settings = configured_settings()
    service.db = SimpleNamespace(
        add=Mock(),
        flush=AsyncMock(),
        scalar=AsyncMock(return_value=None),
        get=AsyncMock(),
        rollback=AsyncMock(),
    )
    service.repo = SimpleNamespace(
        subscription=AsyncMock(return_value=subscription), usage=AsyncMock(return_value=None)
    )
    return service


@pytest.mark.asyncio
async def test_billing_subscription_limits_usage_and_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = billing_service(None)
    created = await service.get_or_create_subscription()
    assert created.plan == "free"
    service.repo.subscription.return_value = created
    service.current_usage = AsyncMock(return_value=400)
    publish = AsyncMock()
    monkeypatch.setattr("app.modules.billing.service.publish_enterprise_event", publish)
    assert await service.reserve_quota("send_email")
    publish.assert_awaited_once()
    service.current_usage.return_value = 500
    with pytest.raises(LimitExceededError):
        await service.check_limits("send_email")
    created.status = "past_due"
    with pytest.raises(LimitExceededError, match="неактивна"):
        await service.check_limits("send_email")
    created.status = "active"
    with pytest.raises(ValueError):
        await service.check_limits("unknown")
    with pytest.raises(ValueError):
        await service.check_limits("send_email", 0)
    with pytest.raises(AppError):
        BillingService._get_limits("missing")

    service.db.scalar.side_effect = [2, 3, 4]
    for metric, expected in (("contacts_stored", 2), ("domains", 3), ("users", 4)):
        assert (
            await BillingService.current_usage(service, metric, created.current_period_start)
            == expected
        )
    usage = UsageLog(
        workspace_id=service.workspace_id,
        metric="emails_sent",
        count=7,
        period_start=created.current_period_start,
        period_end=created.current_period_end,
    )
    service.repo.usage.return_value = usage
    assert (
        await BillingService.current_usage(service, "emails_sent", created.current_period_start)
        == 7
    )
    service.repo.usage.return_value = None
    assert (
        await BillingService.current_usage(service, "api_calls", created.current_period_start) == 0
    )

    service.get_or_create_subscription = AsyncMock(return_value=created)
    service.repo.usage.return_value = None
    incremented = await service.increment_usage("emails_sent", 2)
    assert incremented.count == 2
    service.increment_usage = AsyncMock()
    event = IntegrationEvent(
        workspace_id=service.workspace_id, kind="email.sent", data={"count": 3}
    )
    await service.handle_event(event)
    service.increment_usage.assert_awaited_once_with("emails_sent", 3)
    service.increment_usage.reset_mock()
    await service.update_usage(IntegrationEvent(workspace_id=service.workspace_id, kind="ignored"))
    service.increment_usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_billing_subscribe_cancel_and_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    subscription = make_subscription()
    service = billing_service(subscription)
    service.get_or_create_subscription = AsyncMock(return_value=subscription)
    assert await service.subscribe(SubscribeRequest(plan="free")) is None
    with pytest.raises(AppError):
        await service.subscribe(SubscribeRequest(plan="enterprise"))

    create_payment = AsyncMock(return_value=Checkout("pay_1", "https://checkout", "pending"))
    monkeypatch.setattr(YooKassaProvider, "create_payment", create_payment)
    invoice = await service.subscribe(
        SubscribeRequest(plan="pro", provider="yookassa", idempotency_key="subscribe-yookassa")
    )
    assert invoice and invoice.kind == "initial" and invoice.pdf_url
    monkeypatch.setattr(StripeProvider, "create_payment", create_payment)
    assert await service.subscribe(
        SubscribeRequest(plan="pro", provider="stripe", idempotency_key="subscribe-stripe")
    )
    monkeypatch.setattr(TinkoffProvider, "create_payment", create_payment)
    assert await service.subscribe(
        SubscribeRequest(plan="business", provider="tinkoff", idempotency_key="subscribe-tinkoff")
    )

    subscription.provider = "stripe"
    subscription.provider_subscription_id = "sub_1"
    subscription.auto_renew = True
    cancel = AsyncMock()
    monkeypatch.setattr(StripeProvider, "cancel_subscription", cancel)
    await service.cancel()
    cancel.assert_awaited_once_with("sub_1", immediately=False)
    assert not subscription.auto_renew and subscription.cancel_at == subscription.current_period_end

    paid = Invoice(
        workspace_id=service.workspace_id,
        subscription_id=subscription.id,
        provider="stripe",
        provider_payment_id="pay_2",
        plan="pro",
        amount=Decimal("9900"),
        currency="RUB",
        status="draft",
    )
    service.db.get.return_value = subscription
    await service.apply_paid_invoice(paid, provider_subscription_id="sub_2")
    assert paid.status == "paid" and subscription.auto_renew
    await service.apply_paid_invoice(paid)
    service.db.get.return_value = None
    missing = Invoice(
        subscription_id=uuid4(),
        workspace_id=service.workspace_id,
        provider="yookassa",
        plan="pro",
        amount=Decimal("9900"),
        currency="RUB",
        status="draft",
    )
    with pytest.raises(NotFoundError):
        await service.apply_paid_invoice(missing)


@pytest.mark.asyncio
async def test_billing_payment_and_renewal_idempotence_and_validation() -> None:
    subscription = make_subscription("pro")
    subscription.provider = "stripe"
    subscription.provider_subscription_id = "sub_1"
    service = billing_service(subscription)
    invoice = Invoice(
        id=uuid4(),
        workspace_id=service.workspace_id,
        subscription_id=subscription.id,
        provider="stripe",
        provider_payment_id="cs_1",
        plan="pro",
        amount=Decimal("9900"),
        currency="RUB",
        status="draft",
    )
    service.db.scalar.side_effect = [None, invoice]
    service.db.get.return_value = subscription
    assert await service.process_payment_event(
        "stripe", "evt_1", {}, "cs_1", provider_subscription_id="sub_1"
    )
    service.db.scalar.side_effect = [None, None]
    with pytest.raises(NotFoundError):
        await service.process_payment_event("stripe", "evt_2", {}, "missing")
    service.db.scalar.side_effect = [None, invoice]
    service.db.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    assert not await service.process_payment_event("stripe", "evt_3", {}, "cs_1")
    service.db.flush.side_effect = None

    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = datetime(2026, 11, 1, tzinfo=UTC)
    service.db.scalar.side_effect = [None, None]
    with pytest.raises(NotFoundError):
        await service.process_stripe_renewal(
            "evt_r0",
            {},
            provider_invoice_id="in_0",
            provider_subscription_id="missing",
            amount=Decimal("9900"),
            currency="RUB",
            period_start=start,
            period_end=end,
        )
    service.db.scalar.side_effect = [None, subscription]
    with pytest.raises(AppError):
        await service.process_stripe_renewal(
            "evt_r1",
            {},
            provider_invoice_id="in_1",
            provider_subscription_id="sub_1",
            amount=Decimal("1"),
            currency="RUB",
            period_start=start,
            period_end=end,
        )
    service.db.scalar.side_effect = [None, subscription, Invoice()]
    assert not await service.process_stripe_renewal(
        "evt_r2",
        {},
        provider_invoice_id="in_2",
        provider_subscription_id="sub_1",
        amount=Decimal("9900"),
        currency="RUB",
        period_start=start,
        period_end=end,
    )
    service.db.scalar.side_effect = [None, subscription, None]
    assert await service.process_stripe_renewal(
        "evt_r3",
        {"paid": True},
        provider_invoice_id="in_3",
        provider_subscription_id="sub_1",
        amount=Decimal("9900"),
        currency="RUB",
        period_start=start,
        period_end=end,
    )
    assert subscription.current_period_end == end
    service.db.scalar.side_effect = [PaymentEvent()]
    assert not await service.process_stripe_renewal(
        "evt_r3",
        {},
        provider_invoice_id="in_3",
        provider_subscription_id="sub_1",
        amount=Decimal("9900"),
        currency="RUB",
        period_start=start,
        period_end=end,
    )
    service.db.scalar.side_effect = [None, subscription, None]
    service.db.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    assert not await service.process_stripe_renewal(
        "evt_race",
        {},
        provider_invoice_id="in_race",
        provider_subscription_id="sub_1",
        amount=Decimal("9900"),
        currency="RUB",
        period_start=start,
        period_end=end,
    )
