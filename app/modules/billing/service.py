from __future__ import annotations

import hashlib
import hmac
from calendar import monthrange
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.events import DomainEvent, IntegrationEvent, publish_enterprise_event
from app.core.exceptions import AppError, NotFoundError
from app.modules.audit import audited
from app.modules.billing.models import Invoice, PaymentEvent, Subscription, UsageLog
from app.modules.billing.providers import StripeProvider, TinkoffProvider, YooKassaProvider
from app.modules.billing.repository import BillingRepository
from app.modules.billing.schemas import SubscribeRequest


class LimitExceededError(AppError):
    status_code = 402
    code = "plan_limit_exceeded"


class BillingService:
    LIMITS: ClassVar[dict[str, dict[str, int | None]]] = {
        "free": {"emails_per_month": 500, "contacts": 100, "domains": 1, "users": 1},
        "pro": {"emails_per_month": 25_000, "contacts": 5_000, "domains": 3, "users": 5},
        "business": {
            "emails_per_month": 250_000,
            "contacts": 50_000,
            "domains": 10,
            "users": 20,
        },
        "enterprise": {
            "emails_per_month": None,
            "contacts": None,
            "domains": None,
            "users": None,
        },
    }
    PRICES: ClassVar[dict[str, Decimal]] = {
        "free": Decimal("0.00"),
        "pro": Decimal("9900.00"),
        "business": Decimal("49900.00"),
    }
    ACTION_METRICS: ClassVar[dict[str, str]] = {
        "send_email": "emails_sent",
        "create_contact": "contacts_stored",
        "add_domain": "domains",
        "add_user": "users",
        "api_call": "api_calls",
    }

    def __init__(
        self, db: AsyncSession, workspace_id: UUID, settings: Settings | None = None
    ) -> None:
        self.db, self.workspace_id = db, workspace_id
        self.repo = BillingRepository(db, workspace_id)
        self.settings = settings or get_settings()

    @staticmethod
    def period_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
        now = now or datetime.now(UTC)
        start = datetime(now.year, now.month, 1, tzinfo=UTC)
        days = monthrange(now.year, now.month)[1]
        return start, start.replace(day=days, hour=23, minute=59, second=59, microsecond=999999)

    @staticmethod
    def paid_period(now: datetime | None = None) -> tuple[datetime, datetime]:
        start = now or datetime.now(UTC)
        year = start.year + (1 if start.month == 12 else 0)
        month = 1 if start.month == 12 else start.month + 1
        day = min(start.day, monthrange(year, month)[1])
        return start, start.replace(year=year, month=month, day=day)

    @classmethod
    def _get_limits(cls, plan: str) -> dict[str, int | None]:
        try:
            return cls.LIMITS[plan]
        except KeyError as exc:
            raise AppError(f"Неизвестный тариф: {plan}") from exc

    async def get_or_create_subscription(self) -> Subscription:
        row = await self.repo.subscription()
        if row:
            return row
        start, end = self.period_bounds()
        row = Subscription(
            workspace_id=self.workspace_id,
            plan="free",
            status="active",
            current_period_start=start,
            current_period_end=end,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    def free_test_access(self, plan: str) -> bool:
        return plan == "free" and self.settings.free_plan_test_mode

    def effective_limits(self, plan: str) -> dict[str, int | None]:
        limits = self._get_limits(plan)
        if self.free_test_access(plan):
            return {key: None for key in limits}
        return limits.copy()

    async def _lock_workspace_quota(self) -> None:
        """Lock a quota namespace even before the workspace has a subscription row."""
        if isinstance(self.db, AsyncSession):
            lock_key = int.from_bytes(self.workspace_id.bytes[:8], byteorder="big", signed=True)
            await self.db.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def check_limits(self, action: str, count: int = 1) -> bool:
        if count < 1:
            raise ValueError("count должен быть положительным")
        # The advisory lock also covers a brand-new workspace without a subscription row. It is
        # held until the caller transaction commits, including the protected insert itself.
        await self._lock_workspace_quota()
        subscription = await self.repo.subscription(for_update=True)
        if subscription is None:
            subscription = await self.get_or_create_subscription()
        if subscription.status not in {"active", "trialing"}:
            raise LimitExceededError("Подписка неактивна")
        metric = self.ACTION_METRICS.get(action)
        if not metric:
            raise ValueError(f"Неизвестное действие биллинга: {action}")
        limit_key = {
            "emails_sent": "emails_per_month",
            "contacts_stored": "contacts",
            "domains": "domains",
            "users": "users",
            "api_calls": "api_calls",
        }[metric]
        limit = self.effective_limits(subscription.plan).get(limit_key)
        if limit is None:
            return True
        current = await self.current_usage(metric, subscription.current_period_start)
        labels = {
            "emails_sent": "писем",
            "contacts_stored": "контактов",
            "domains": "доменов",
            "users": "пользователей",
            "api_calls": "API-запросов",
        }
        if current + count > limit:
            raise LimitExceededError(f"Превышен лимит {labels[metric]} тарифа {subscription.plan}")
        if current + count >= max(1, int(limit * 0.8)):
            await publish_enterprise_event(
                self.db,
                IntegrationEvent(
                    workspace_id=self.workspace_id,
                    resource_type="subscription",
                    resource_id=subscription.id,
                    data={
                        "metric": metric,
                        "used": current,
                        "requested": count,
                        "limit": limit,
                        "message": f"Использовано не менее 80% лимита {labels[metric]}",
                    },
                    kind="billing.limit_warning",
                ),
            )
        return True

    async def reserve_quota(self, action: str, count: int = 1) -> bool:
        """Serialize quota check on the subscription row for the caller transaction."""
        return await self.check_limits(action, count)

    async def current_usage(self, metric: str, period_start: datetime) -> int:
        # Gauges are reconciled from source tables, so limits remain correct after deployment.
        if metric == "contacts_stored":
            from app.modules.contacts.models import Contact

            value = await self.db.scalar(
                select(func.count())
                .select_from(Contact)
                .where(Contact.workspace_id == self.workspace_id)
            )
            return int(value or 0)
        if metric == "domains":
            from app.modules.domains.models import SendingDomain

            value = await self.db.scalar(
                select(func.count())
                .select_from(SendingDomain)
                .where(SendingDomain.workspace_id == self.workspace_id)
            )
            return int(value or 0)
        if metric == "users":
            from app.modules.users.models import WorkspaceMember

            value = await self.db.scalar(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == self.workspace_id)
            )
            return int(value or 0)
        usage = await self.repo.usage(metric, period_start)
        if usage:
            return usage.count
        return 0

    async def increment_usage(self, metric: str, count: int = 1) -> UsageLog:
        subscription = await self.get_or_create_subscription()
        row = await self.repo.usage(metric, subscription.current_period_start, for_update=True)
        if not row:
            row = UsageLog(
                workspace_id=self.workspace_id,
                metric=metric,
                count=0,
                period_start=subscription.current_period_start,
                period_end=subscription.current_period_end,
            )
            self.db.add(row)
            await self.db.flush()
        row.count += count
        await self.db.flush()
        return row

    async def update_usage(self, event: DomainEvent) -> None:
        metric = {
            "email.sent": "emails_sent",
            "contact.created": "contacts_stored",
            "domain.created": "domains",
            "workspace.member_added": "users",
            "api.called": "api_calls",
        }.get(event.event_type)
        if metric:
            await self.increment_usage(metric, int(event.data.get("count", 1)))

    async def handle_event(self, event: DomainEvent) -> None:
        await self.update_usage(event)

    def provider_idempotency_key(self, provider: str, client_key: str) -> str:
        """Derive a provider-safe key while retaining the client key for tenant dedup."""
        message = f"billing:subscribe:{provider}:{self.workspace_id}:{client_key}".encode()
        digest = hmac.new(
            self.settings.app_secret_key.encode(), message, hashlib.sha256
        ).hexdigest()
        # Tinkoff OrderId is limited to 36 characters. 132 bits remains collision resistant.
        return f"pbm_{digest[:32]}"

    @audited("billing.subscription_requested", "subscription")
    async def subscribe(self, data: SubscribeRequest) -> Invoice | None:
        await self._lock_workspace_quota()
        subscription = await self.repo.subscription(for_update=True)
        if subscription is None:
            subscription = await self.get_or_create_subscription()
        if data.plan == "enterprise":
            raise AppError("Для тарифа Enterprise свяжитесь с отделом продаж")
        if data.idempotency_key:
            existing = await self.db.scalar(
                select(Invoice).where(
                    Invoice.workspace_id == self.workspace_id,
                    Invoice.idempotency_key == data.idempotency_key,
                )
            )
            if existing:
                if existing.plan != data.plan or existing.provider != data.provider:
                    raise AppError("Idempotency-Key уже использован для другого платежа")
                return existing
        attached_stripe = bool(
            subscription.provider == "stripe"
            and subscription.provider_subscription_id
            and subscription.status != "cancelled"
        )
        if data.plan == "free":
            if attached_stripe:
                await self._cancel_stripe(subscription, immediately=True)
            subscription.plan = "free"
            subscription.status = "active"
            subscription.provider = None
            subscription.provider_subscription_id = None
            subscription.auto_renew = False
            subscription.cancel_at = None
            return None
        if not data.idempotency_key:
            raise AppError("Для оплаты требуется Idempotency-Key")
        if attached_stripe:
            if data.provider == "stripe" and data.plan == subscription.plan:
                raise AppError("Stripe subscription для этого тарифа уже активна")
            # Provider cancellation must succeed before a replacement checkout can be created.
            # Keep the old provider id until the new provider payment is confirmed.
            await self._cancel_stripe(subscription, immediately=True)
        amount = self.PRICES[data.plan]
        return_url = data.return_url or f"{self.settings.public_base_url}/billing"
        description = f"Premium B2B Mailer — тариф {data.plan} на 1 месяц"
        provider_key = self.provider_idempotency_key(data.provider, data.idempotency_key)
        if data.provider == "yookassa":
            checkout = await YooKassaProvider(self.settings).create_payment(
                amount, "RUB", description, return_url, provider_key
            )
        elif data.provider == "stripe":
            checkout = await StripeProvider(self.settings).create_payment(
                amount, "RUB", description, return_url, provider_key
            )
        else:
            checkout = await TinkoffProvider(self.settings).create_payment(
                amount, "RUB", description, return_url, provider_key
            )
        invoice = Invoice(
            workspace_id=self.workspace_id,
            subscription_id=subscription.id,
            provider=data.provider,
            provider_payment_id=checkout.payment_id,
            idempotency_key=data.idempotency_key,
            plan=data.plan,
            amount=amount,
            currency="RUB",
            status="draft",
            # YooKassa and Tinkoff integrations are deliberately one-off payments: a
            # same-plan purchase extends the already paid term only after its callback.
            # Stripe uses its provider subscription and subsequent invoice.paid events.
            kind=(
                "renewal"
                if data.provider != "stripe"
                and subscription.plan == data.plan
                and subscription.status == "active"
                else "initial"
            ),
            checkout_url=checkout.url,
        )
        self.db.add(invoice)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            # Never resolve a provider identity collision to another workspace.
            await self.db.rollback()
            race_invoice: Invoice | None = await self.db.scalar(
                select(Invoice).where(
                    Invoice.workspace_id == self.workspace_id,
                    Invoice.idempotency_key == data.idempotency_key,
                )
            )
            if (
                race_invoice
                and race_invoice.plan == data.plan
                and race_invoice.provider == data.provider
            ):
                return race_invoice
            raise AppError("Провайдер вернул уже используемый идентификатор платежа") from exc
        invoice.pdf_url = (
            f"{self.settings.public_base_url}/api/v1/billing/invoices/{invoice.id}.pdf"
        )
        return invoice

    async def _cancel_stripe(self, subscription: Subscription, *, immediately: bool) -> None:
        provider_subscription_id = subscription.provider_subscription_id
        if not provider_subscription_id:
            raise AppError("Stripe subscription id отсутствует")
        await StripeProvider(self.settings).cancel_subscription(
            provider_subscription_id, immediately=immediately
        )
        # These fields change only after Stripe confirms cancellation. The provider id remains
        # available for reconciliation until a confirmed replacement/free downgrade is stored.
        subscription.auto_renew = False
        subscription.cancel_at = (
            datetime.now(UTC) if immediately else subscription.current_period_end
        )

    @audited("billing.subscription_cancelled", "subscription")
    async def cancel(self) -> Subscription:
        subscription = await self.get_or_create_subscription()
        if (
            subscription.provider == "stripe"
            and subscription.provider_subscription_id
            and subscription.status != "cancelled"
        ):
            await self._cancel_stripe(subscription, immediately=False)
        else:
            subscription.auto_renew = False
            subscription.cancel_at = subscription.current_period_end
        await self.db.flush()
        return subscription

    async def apply_paid_invoice(
        self,
        invoice: Invoice,
        *,
        provider_subscription_id: str | None = None,
        period: tuple[datetime, datetime] | None = None,
    ) -> None:
        if invoice.status == "paid":
            return
        subscription = await self.db.get(Subscription, invoice.subscription_id)
        if not subscription:
            raise NotFoundError("Подписка счёта не найдена")
        if (
            subscription.workspace_id != invoice.workspace_id
            or invoice.workspace_id != self.workspace_id
        ):
            raise AppError("Счёт не принадлежит подписке workspace")
        now = datetime.now(UTC)
        if period:
            start, end = period
        elif (
            invoice.provider != "stripe"
            and invoice.kind == "renewal"
            and subscription.status == "active"
            and subscription.current_period_end > now
        ):
            start = subscription.current_period_end
            _, end = self.paid_period(start)
        else:
            start, end = self.paid_period(now)
        invoice.status = "paid"
        invoice.paid_at = now
        invoice.period_start = start
        invoice.period_end = end
        subscription.plan = invoice.plan
        subscription.status = "active"
        subscription.provider = invoice.provider
        if invoice.provider == "stripe" and not provider_subscription_id:
            raise AppError("Stripe subscription id отсутствует в подтверждённом платеже")
        subscription.provider_subscription_id = (
            provider_subscription_id if invoice.provider == "stripe" else None
        )
        subscription.auto_renew = bool(
            invoice.provider == "stripe" and subscription.provider_subscription_id
        )
        subscription.current_period_start = start
        subscription.current_period_end = end
        subscription.cancel_at = None

    async def process_payment_event(
        self,
        provider: str,
        event_id: str,
        payload: dict[str, object],
        payment_id: str,
        *,
        provider_subscription_id: str | None = None,
    ) -> bool:
        existing = await self.db.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == provider,
                PaymentEvent.external_event_id == event_id,
            )
        )
        if existing:
            return False
        invoice = await self.db.scalar(
            select(Invoice)
            .where(
                Invoice.workspace_id == self.workspace_id,
                Invoice.provider == provider,
                Invoice.provider_payment_id == payment_id,
            )
            .with_for_update()
        )
        if not invoice:
            raise NotFoundError("Счёт для платежа не найден")
        self.db.add(PaymentEvent(provider=provider, external_event_id=event_id, payload=payload))
        await self.apply_paid_invoice(invoice, provider_subscription_id=provider_subscription_id)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            return False
        return True

    async def process_stripe_renewal(
        self,
        event_id: str,
        payload: dict[str, object],
        *,
        provider_invoice_id: str,
        provider_subscription_id: str,
        amount: Decimal,
        currency: str,
        period_start: datetime,
        period_end: datetime,
    ) -> bool:
        if await self.db.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == "stripe",
                PaymentEvent.external_event_id == event_id,
            )
        ):
            return False
        subscription = await self.db.scalar(
            select(Subscription)
            .where(
                Subscription.workspace_id == self.workspace_id,
                Subscription.provider == "stripe",
                Subscription.provider_subscription_id == provider_subscription_id,
            )
            .with_for_update()
        )
        if not subscription:
            raise NotFoundError("Stripe subscription не найдена")
        if not subscription.auto_renew:
            raise AppError("Stripe subscription отменена; renewal отклонён")
        expected = self.PRICES.get(subscription.plan)
        if expected is None or amount != expected or currency != "RUB":
            raise AppError("Сумма Stripe renewal не совпадает с тарифом")
        existing_invoice = await self.db.scalar(
            select(Invoice).where(
                Invoice.provider == "stripe",
                Invoice.provider_invoice_id == provider_invoice_id,
            )
        )
        if existing_invoice:
            return False
        invoice = Invoice(
            workspace_id=self.workspace_id,
            subscription_id=subscription.id,
            provider="stripe",
            provider_payment_id=provider_invoice_id,
            provider_invoice_id=provider_invoice_id,
            plan=subscription.plan,
            kind="renewal",
            amount=amount,
            currency=currency,
            status="paid",
            paid_at=datetime.now(UTC),
            period_start=period_start,
            period_end=period_end,
        )
        self.db.add(invoice)
        self.db.add(PaymentEvent(provider="stripe", external_event_id=event_id, payload=payload))
        subscription.status = "active"
        subscription.auto_renew = True
        subscription.current_period_start = period_start
        subscription.current_period_end = period_end
        try:
            await self.db.flush()
        except IntegrityError:
            # Concurrent duplicate provider callbacks converge to the already committed event.
            await self.db.rollback()
            return False
        return True
