import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dependencies import TenantContext, get_tenant_context
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.database import get_db
from app.modules.audit.service import _minimal_pdf
from app.modules.billing.models import Invoice, Subscription
from app.modules.billing.providers import StripeProvider, TinkoffProvider, YooKassaProvider
from app.modules.billing.repository import BillingRepository
from app.modules.billing.schemas import (
    CheckoutResponse,
    InvoiceResponse,
    SubscribeRequest,
    SubscriptionResponse,
    UsageItem,
    UsageResponse,
)
from app.modules.billing.service import BillingService
from app.shared.dto import MessageResponse

router = APIRouter(prefix="/billing", tags=["billing"])


def require_billing_admin(tenant: TenantContext) -> None:
    if tenant.role not in {"owner", "admin"}:
        raise PermissionDeniedError("Управление тарифом доступно владельцу и администраторам")


@router.get("/subscription", response_model=SubscriptionResponse)
async def subscription(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> SubscriptionResponse:
    return SubscriptionResponse.model_validate(
        await BillingService(db, tenant.workspace_id).get_or_create_subscription()
    )


@router.post("/subscribe", response_model=CheckoutResponse)
async def subscribe(
    data: SubscribeRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    require_billing_admin(tenant)
    if idempotency_key and data.idempotency_key and idempotency_key != data.idempotency_key:
        raise AppError("Idempotency-Key в header и body не совпадает")
    if idempotency_key:
        data = SubscribeRequest.model_validate(
            {**data.model_dump(), "idempotency_key": idempotency_key}
        )
    invoice = await BillingService(db, tenant.workspace_id).subscribe(data)
    if invoice is None:
        return CheckoutResponse(invoice_id=UUID(int=0), status="active", checkout_url=None)
    return CheckoutResponse(
        invoice_id=invoice.id, status=invoice.status, checkout_url=invoice.checkout_url
    )


@router.post("/cancel", response_model=SubscriptionResponse)
async def cancel(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> SubscriptionResponse:
    require_billing_admin(tenant)
    return SubscriptionResponse.model_validate(
        await BillingService(db, tenant.workspace_id).cancel()
    )


@router.get("/usage", response_model=UsageResponse)
async def usage(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> UsageResponse:
    service = BillingService(db, tenant.workspace_id)
    subscription = await service.get_or_create_subscription()
    limits = service.effective_limits(subscription.plan)
    pairs = (
        ("emails_sent", "emails_per_month"),
        ("contacts_stored", "contacts"),
        ("domains", "domains"),
        ("users", "users"),
    )
    items = []
    for metric, limit_key in pairs:
        count = await service.current_usage(metric, subscription.current_period_start)
        limit = limits[limit_key]
        items.append(
            UsageItem(
                metric=metric,
                count=count,
                limit=limit,
                percent=round(count / limit * 100, 2) if limit else None,
            )
        )
    return UsageResponse(
        plan=subscription.plan,
        free_plan_test_mode=service.free_test_access(subscription.plan),
        period_start=subscription.current_period_start,
        period_end=subscription.current_period_end,
        items=items,
    )


@router.get("/invoices", response_model=list[InvoiceResponse])
async def invoices(
    tenant: TenantContext = Depends(get_tenant_context), db: AsyncSession = Depends(get_db)
) -> list[InvoiceResponse]:
    return [
        InvoiceResponse.model_validate(row)
        for row in await BillingRepository(db, tenant.workspace_id).invoices()
    ]


@router.get("/invoices/{invoice_id}.pdf")
async def invoice_pdf(
    invoice_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    invoice = await db.scalar(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.workspace_id == tenant.workspace_id)
    )
    if not invoice:
        raise NotFoundError("Счёт не найден")
    content = _minimal_pdf(
        [
            "Premium B2B Mailer invoice",
            f"Invoice: {invoice.id}",
            f"Plan: {invoice.plan}",
            f"Amount: {invoice.amount} {invoice.currency}",
            f"Status: {invoice.status}",
        ]
    )
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{invoice.id}.pdf"'},
    )


@router.post("/webhook/stripe", response_model=MessageResponse)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    body = await request.body()
    payload = StripeProvider(get_settings()).verify_webhook(body, stripe_signature)
    event_type = payload.get("type")
    if event_type not in {"checkout.session.completed", "invoice.paid"}:
        return MessageResponse(message="Событие принято")
    event_id = str(payload.get("id", ""))
    if not event_id:
        raise AppError("Stripe event id отсутствует")
    obj = payload.get("data", {})
    session = obj.get("object", {}) if isinstance(obj, dict) else {}
    if not isinstance(session, dict):
        raise AppError("Некорректный объект Stripe")
    if event_type == "invoice.paid":
        if session.get("billing_reason") != "subscription_cycle":
            return MessageResponse(message="Первичный invoice подтверждается Checkout Session")
        subscription_id = str(session.get("subscription", ""))
        provider_invoice_id = str(session.get("id", ""))
        if not subscription_id or not provider_invoice_id:
            raise AppError("Stripe renewal не содержит subscription или invoice id")
        subscription = await db.scalar(
            select(Subscription)
            .where(
                Subscription.provider == "stripe",
                Subscription.provider_subscription_id == subscription_id,
            )
            .with_for_update()
        )
        if not subscription:
            raise NotFoundError("Stripe subscription не найдена")
        lines = session.get("lines", {})
        line_data = lines.get("data", []) if isinstance(lines, dict) else []
        period = (
            line_data[0].get("period", {}) if line_data and isinstance(line_data[0], dict) else {}
        )
        try:
            amount = Decimal(str(session["amount_paid"])) / 100
            currency = str(session["currency"]).upper()
            period_start = datetime.fromtimestamp(int(period["start"]), tz=UTC)
            period_end = datetime.fromtimestamp(int(period["end"]), tz=UTC)
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise AppError("Stripe renewal содержит некорректный период или сумму") from exc
        await BillingService(db, subscription.workspace_id).process_stripe_renewal(
            event_id,
            payload,
            provider_invoice_id=provider_invoice_id,
            provider_subscription_id=subscription_id,
            amount=amount,
            currency=currency,
            period_start=period_start,
            period_end=period_end,
        )
        return MessageResponse(message="Продление обработано")
    if session.get("payment_status") != "paid":
        return MessageResponse(message="Платёж ещё не завершён")
    payment_id = str(session.get("id", ""))
    provider_subscription_id = str(session.get("subscription", ""))
    if not provider_subscription_id:
        raise AppError("Stripe Checkout не содержит recurring subscription id")
    invoice = await db.scalar(
        select(Invoice)
        .where(Invoice.provider == "stripe", Invoice.provider_payment_id == payment_id)
        .with_for_update()
    )
    if not invoice:
        raise NotFoundError("Счёт Stripe не найден")
    amount_total = session.get("amount_total")
    currency = str(session.get("currency", "")).upper()
    if (
        amount_total is None
        or Decimal(str(amount_total)) / 100 != invoice.amount
        or currency != invoice.currency
    ):
        raise AppError("Сумма платежа Stripe не совпадает со счётом")
    await BillingService(db, invoice.workspace_id).process_payment_event(
        "stripe",
        event_id,
        payload,
        payment_id,
        provider_subscription_id=provider_subscription_id,
    )
    return MessageResponse(message="Событие обработано")


@router.post("/webhook/yookassa", response_model=MessageResponse)
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> MessageResponse:
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AppError("Некорректный payload ЮKassa") from exc
    obj = payload.get("object", {}) if isinstance(payload, dict) else {}
    payment_id = str(obj.get("id", "")) if isinstance(obj, dict) else ""
    if not payment_id:
        raise AppError("В событии ЮKassa отсутствует payment id")
    # ЮKassa does not sign these callbacks: re-fetching the object is the trust boundary.
    trusted = await YooKassaProvider(get_settings()).fetch_payment(payment_id)
    if trusted.get("status") != "succeeded" or not trusted.get("paid"):
        return MessageResponse(message="Платёж ещё не завершён")
    invoice = await db.scalar(
        select(Invoice)
        .where(Invoice.provider == "yookassa", Invoice.provider_payment_id == payment_id)
        .with_for_update()
    )
    if not invoice:
        raise NotFoundError("Счёт ЮKassa не найден")
    amount = trusted.get("amount", {})
    try:
        value = Decimal(str(amount["value"]))  # type: ignore[index]
        currency = str(amount["currency"])  # type: ignore[index]
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise AppError("ЮKassa вернула некорректную сумму") from exc
    if value != invoice.amount or currency != invoice.currency:
        raise AppError("Сумма платежа ЮKassa не совпадает со счётом")
    event_id = hashlib.sha256(body).hexdigest()
    await BillingService(db, invoice.workspace_id).process_payment_event(
        "yookassa", event_id, payload, payment_id
    )
    return MessageResponse(message="Событие обработано")


@router.post("/webhook/tinkoff", response_model=MessageResponse)
async def tinkoff_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> MessageResponse:
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AppError("Некорректный payload Tinkoff Kassa") from exc
    if not isinstance(payload, dict):
        raise AppError("Некорректный payload Tinkoff Kassa")
    TinkoffProvider(get_settings()).verify_webhook(payload)
    if payload.get("Status") != "CONFIRMED" or payload.get("Success") is not True:
        return MessageResponse(message="Платёж ещё не завершён")
    payment_id = str(payload.get("PaymentId", ""))
    invoice = await db.scalar(
        select(Invoice)
        .where(Invoice.provider == "tinkoff", Invoice.provider_payment_id == payment_id)
        .with_for_update()
    )
    if not invoice:
        raise NotFoundError("Счёт Tinkoff Kassa не найден")
    try:
        amount = Decimal(str(payload["Amount"])) / 100
    except (KeyError, InvalidOperation) as exc:
        raise AppError("Tinkoff Kassa вернула некорректную сумму") from exc
    if amount != invoice.amount:
        raise AppError("Сумма платежа Tinkoff Kassa не совпадает со счётом")
    await BillingService(db, invoice.workspace_id).process_payment_event(
        "tinkoff", hashlib.sha256(body).hexdigest(), payload, payment_id
    )
    return MessageResponse(message="Событие обработано")
