from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.config import Settings
from app.core.exceptions import AppError


class PaymentProviderError(AppError):
    code = "payment_provider_error"


@dataclass(frozen=True)
class Checkout:
    payment_id: str
    url: str | None
    status: str


class YooKassaProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings, self.client = settings, client

    async def create_payment(
        self,
        amount: Decimal,
        currency: str,
        description: str,
        return_url: str,
        idempotency_key: str,
    ) -> Checkout:
        if not self.settings.yookassa_shop_id or not self.settings.yookassa_secret_key:
            raise PaymentProviderError("ЮKassa не настроена")
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=15)
        try:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(self.settings.yookassa_shop_id, self.settings.yookassa_secret_key),
                headers={"Idempotence-Key": idempotency_key},
                json={
                    "amount": {"value": f"{amount:.2f}", "currency": currency},
                    "capture": True,
                    "confirmation": {"type": "redirect", "return_url": return_url},
                    "description": description,
                },
            )
            response.raise_for_status()
            body = response.json()
            return Checkout(
                str(body["id"]),
                body.get("confirmation", {}).get("confirmation_url"),
                str(body["status"]),
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise PaymentProviderError("Не удалось создать платёж ЮKassa") from exc
        finally:
            if owned:
                await client.aclose()

    async def fetch_payment(self, payment_id: str) -> dict[str, object]:
        if not self.settings.yookassa_shop_id or not self.settings.yookassa_secret_key:
            raise PaymentProviderError("ЮKassa не настроена")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"https://api.yookassa.ru/v3/payments/{payment_id}",
                auth=(self.settings.yookassa_shop_id, self.settings.yookassa_secret_key),
            )
            response.raise_for_status()
            return dict(response.json())


class StripeProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings, self.client = settings, client

    async def create_payment(
        self,
        amount: Decimal,
        currency: str,
        description: str,
        return_url: str,
        idempotency_key: str,
    ) -> Checkout:
        if not self.settings.stripe_secret_key:
            raise PaymentProviderError("Stripe не настроен")
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=15)
        try:
            response = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                headers={
                    "Authorization": f"Bearer {self.settings.stripe_secret_key}",
                    "Idempotency-Key": idempotency_key,
                },
                data={
                    "mode": "subscription",
                    "success_url": return_url,
                    "cancel_url": return_url,
                    "line_items[0][price_data][currency]": currency.casefold(),
                    "line_items[0][price_data][unit_amount]": str(int(amount * 100)),
                    "line_items[0][price_data][product_data][name]": description,
                    "line_items[0][price_data][recurring][interval]": "month",
                    "line_items[0][quantity]": "1",
                },
            )
            response.raise_for_status()
            body = response.json()
            return Checkout(str(body["id"]), body.get("url"), "pending")
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise PaymentProviderError("Не удалось создать платёж Stripe") from exc
        finally:
            if owned:
                await client.aclose()

    async def cancel_subscription(
        self, subscription_id: str, *, immediately: bool = False
    ) -> dict[str, object]:
        if not self.settings.stripe_secret_key:
            raise PaymentProviderError("Stripe не настроен")
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=15)
        try:
            url = f"https://api.stripe.com/v1/subscriptions/{subscription_id}"
            mode = "immediate" if immediately else "period_end"
            headers = {
                "Authorization": f"Bearer {self.settings.stripe_secret_key}",
                "Idempotency-Key": f"cancel:{subscription_id}:{mode}",
            }
            if immediately:
                response = await client.delete(url, headers=headers)
            else:
                response = await client.post(
                    url, headers=headers, data={"cancel_at_period_end": "true"}
                )
            response.raise_for_status()
            body = dict(response.json())
            confirmed = (
                body.get("status") == "canceled"
                if immediately
                else body.get("cancel_at_period_end") is True or body.get("status") == "canceled"
            )
            if not confirmed:
                raise PaymentProviderError("Stripe не подтвердил отмену подписки")
            return body
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise PaymentProviderError("Не удалось отменить подписку Stripe") from exc
        finally:
            if owned:
                await client.aclose()

    def verify_webhook(self, body: bytes, signature_header: str) -> dict[str, object]:
        if not self.settings.stripe_webhook_secret:
            raise PaymentProviderError("Stripe webhook secret не настроен")
        values: dict[str, list[str]] = {}
        for part in signature_header.split(","):
            key, _, value = part.partition("=")
            values.setdefault(key, []).append(value)
        try:
            timestamp = int(values["t"][0])
            signatures = values["v1"]
        except (KeyError, ValueError, IndexError) as exc:
            raise PaymentProviderError("Некорректная подпись Stripe") from exc
        if abs(time.time() - timestamp) > self.settings.stripe_webhook_tolerance_seconds:
            raise PaymentProviderError("Подпись Stripe устарела")
        expected = hmac.new(
            self.settings.stripe_webhook_secret.encode(),
            f"{timestamp}.".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
            raise PaymentProviderError("Неверная подпись Stripe")
        try:
            return dict(json.loads(body))
        except (json.JSONDecodeError, TypeError) as exc:
            raise PaymentProviderError("Некорректный payload Stripe") from exc


class TinkoffProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings, self.client = settings, client

    def token(self, payload: dict[str, object]) -> str:
        values = {
            key: value
            for key, value in payload.items()
            if key != "Token" and not isinstance(value, (dict, list))
        }
        values["Password"] = self.settings.tinkoff_password
        source = "".join(str(values[key]) for key in sorted(values))
        return hashlib.sha256(source.encode()).hexdigest()

    async def create_payment(
        self,
        amount: Decimal,
        currency: str,
        description: str,
        return_url: str,
        idempotency_key: str,
    ) -> Checkout:
        if not self.settings.tinkoff_terminal_key or not self.settings.tinkoff_password:
            raise PaymentProviderError("Tinkoff Kassa не настроена")
        if currency != "RUB":
            raise PaymentProviderError("Tinkoff Kassa настроена только для RUB")
        payload: dict[str, object] = {
            "TerminalKey": self.settings.tinkoff_terminal_key,
            "Amount": int(amount * 100),
            "OrderId": idempotency_key,
            "Description": description,
            "SuccessURL": return_url,
            "FailURL": return_url,
        }
        payload["Token"] = self.token(payload)
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=15)
        try:
            response = await client.post("https://securepay.tinkoff.ru/v2/Init", json=payload)
            response.raise_for_status()
            body = response.json()
            if not body.get("Success"):
                raise PaymentProviderError("Tinkoff Kassa отклонила создание платежа")
            return Checkout(str(body["PaymentId"]), body.get("PaymentURL"), "pending")
        except PaymentProviderError:
            raise
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise PaymentProviderError("Не удалось создать платёж Tinkoff Kassa") from exc
        finally:
            if owned:
                await client.aclose()

    def verify_webhook(self, payload: dict[str, object]) -> None:
        token = str(payload.get("Token", ""))
        if not token or not hmac.compare_digest(token, self.token(payload)):
            raise PaymentProviderError("Неверная подпись Tinkoff Kassa")
