from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import ssl
from base64 import urlsafe_b64encode
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpcore
import httpx
from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.events import DomainEvent
from app.core.exceptions import AppError, NotFoundError
from app.modules.audit import audited
from app.modules.webhooks.models import Webhook, WebhookDelivery, WebhookOutbox
from app.modules.webhooks.repository import WebhookRepository
from app.modules.webhooks.schemas import WebhookCreate, WebhookUpdate


class UnsafeWebhookURLError(AppError):
    code = "unsafe_webhook_url"


class WebhookDeliveryError(Exception):
    pass


def canonical_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def encrypt_secret(secret: str, key: str) -> str:
    digest = hashlib.sha256(key.encode()).digest()
    return Fernet(urlsafe_b64encode(digest)).encrypt(secret.encode()).decode()


def decrypt_secret(secret: str, key: str) -> str:
    digest = hashlib.sha256(key.encode()).digest()
    return Fernet(urlsafe_b64encode(digest)).decrypt(secret.encode()).decode()


def validate_webhook_url(url: str, *, allow_private: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise UnsafeWebhookURLError("Некорректный URL вебхука")
    if parsed.scheme != "https" and not allow_private:
        raise UnsafeWebhookURLError("Для webhook URL требуется HTTPS")
    hostname = parsed.hostname.casefold()
    if hostname in {"localhost", "localhost.localdomain"} and not allow_private:
        raise UnsafeWebhookURLError("Локальные адреса запрещены")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not allow_private and not address.is_global:
        raise UnsafeWebhookURLError("Приватные и служебные адреса запрещены")


Resolver = Callable[[str, int], Awaitable[list[str]]]


async def _system_resolver(hostname: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
    )
    return sorted({str(info[4][0]) for info in infos})


def _validate_public_addresses(addresses: Iterable[str]) -> list[str]:
    normalized = sorted({str(ipaddress.ip_address(address)) for address in addresses})
    if not normalized or any(not ipaddress.ip_address(address).is_global for address in normalized):
        raise UnsafeWebhookURLError("Webhook host указывает на приватную сеть")
    return normalized


async def validate_resolved_target(
    url: str, *, allow_private: bool = False, resolver: Resolver | None = None
) -> str:
    validate_webhook_url(url, allow_private=allow_private)
    parsed = urlparse(url)
    hostname = parsed.hostname
    assert hostname is not None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if allow_private:
        return hostname
    try:
        literal = ipaddress.ip_address(hostname)
        return _validate_public_addresses([str(literal)])[0]
    except ValueError:
        pass
    resolve = resolver or _system_resolver
    try:
        # Resolve twice and validate every A/AAAA response. The second, validated answer is
        # pinned into the socket transport, so a third DNS answer can never redirect the connect.
        _validate_public_addresses(await resolve(hostname, port))
        second = _validate_public_addresses(await resolve(hostname, port))
    except OSError as exc:
        raise UnsafeWebhookURLError("Webhook host не разрешается") from exc
    return second[0]


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connects only to a pre-validated address while preserving hostname TLS/SNI."""

    def __init__(
        self,
        hostname: str,
        pinned_ip: str,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self.hostname = hostname.casefold().rstrip(".")
        self.pinned_ip = str(ipaddress.ip_address(pinned_ip))
        self.backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 -- httpcore interface
        local_address: str | None = None,
        socket_options: Iterable[tuple[object, ...]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if host.casefold().rstrip(".") != self.hostname:
            raise httpcore.ConnectError("Pinned webhook transport rejected another host")
        if not ipaddress.ip_address(self.pinned_ip).is_global:
            raise httpcore.ConnectError("Pinned webhook address is not public")
        stream = await self.backend.connect_tcp(
            self.pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,  # type: ignore[arg-type]
        )
        peer = stream.get_extra_info("server_addr")
        try:
            peer_ip = str(ipaddress.ip_address(str(peer[0])))
        except (TypeError, ValueError, IndexError) as exc:
            await stream.aclose()
            raise httpcore.ConnectError("Cannot verify webhook peer address") from exc
        if peer_ip != self.pinned_ip:
            await stream.aclose()
            raise httpcore.ConnectError("Webhook peer address differs from pinned address")
        return stream

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 -- httpcore interface
        socket_options: Iterable[tuple[object, ...]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are forbidden for webhooks")

    async def sleep(self, seconds: float) -> None:
        await self.backend.sleep(seconds)


class PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self, hostname: str, pinned_ip: str) -> None:
        super().__init__(verify=True, trust_env=False, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            max_connections=1,
            max_keepalive_connections=0,
            network_backend=PinnedNetworkBackend(hostname, pinned_ip),
            retries=0,
        )


class WebhookService:
    def __init__(
        self, db: AsyncSession, workspace_id: UUID, settings: Settings | None = None
    ) -> None:
        self.db, self.workspace_id = db, workspace_id
        self.repo = WebhookRepository(db, workspace_id)
        self.settings = settings or get_settings()

    # The returned tuple contains the one-time plaintext signing secret. Never serialize it.
    @audited("webhook.created", "webhook", log_result=False)
    async def create(self, data: WebhookCreate) -> tuple[Webhook, str]:
        url = str(data.url)
        validate_webhook_url(url, allow_private=self.settings.webhook_allow_private_urls)
        plain_secret = secrets.token_hex(32)
        row = await self.repo.add(
            Webhook(
                workspace_id=self.workspace_id,
                name=data.name,
                url=url,
                events=data.events,
                secret=encrypt_secret(plain_secret, self.settings.app_secret_key),
            )
        )
        return row, plain_secret

    @audited("webhook.updated", "webhook")
    async def update(self, webhook_id: UUID, data: WebhookUpdate) -> Webhook:
        row = await self.repo.get(webhook_id)
        if not row:
            raise NotFoundError("Вебхук не найден")
        values = data.model_dump(exclude_unset=True)
        if values.get("url") is not None:
            values["url"] = str(values["url"])
            validate_webhook_url(
                values["url"], allow_private=self.settings.webhook_allow_private_urls
            )
        for key, value in values.items():
            setattr(row, key, value)
        await self.db.flush()
        return row

    @audited("webhook.deleted", "webhook")
    async def delete(self, webhook_id: UUID) -> None:
        row = await self.repo.get(webhook_id)
        if not row:
            raise NotFoundError("Вебхук не найден")
        await self.db.execute(delete(Webhook).where(Webhook.id == row.id))


class WebhookDispatcher:
    def __init__(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.db, self.workspace_id = db, workspace_id
        self.repo = WebhookRepository(db, workspace_id)
        self.settings = settings or get_settings()
        self.client = client

    @staticmethod
    def _sign_payload(payload: dict[str, object], secret: str) -> str:
        signature = hmac.new(
            secret.encode(), canonical_payload(payload), hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"

    async def dispatch(
        self, event_type: str, payload: dict[str, object], event_id: UUID | None = None
    ) -> list[WebhookDelivery]:
        event_id = event_id or uuid4()
        envelope: dict[str, object] = {
            "id": str(event_id),
            "type": event_type,
            "created_at": datetime.now(UTC).isoformat(),
            "data": payload,
        }
        deliveries: list[WebhookDelivery] = []
        for webhook in await self.repo.get_by_event(event_type):
            existing = await self.db.scalar(
                select(WebhookDelivery).where(
                    WebhookDelivery.webhook_id == webhook.id,
                    WebhookDelivery.event_id == event_id,
                )
            )
            if existing:
                deliveries.append(existing)
                continue
            delivery = WebhookDelivery(
                webhook_id=webhook.id,
                event_id=event_id,
                event_type=event_type,
                payload=envelope,
            )
            self.db.add(delivery)
            await self.db.flush()
            self.db.add(WebhookOutbox(delivery_id=delivery.id))
            deliveries.append(delivery)
        return deliveries

    async def handle_event(self, event: DomainEvent) -> None:
        # Dispatch only writes delivery+outbox rows in the caller transaction. A separate
        # outbox drainer can observe them only after commit and then publishes Celery tasks.
        await self.dispatch(event.event_type, event.data, event.event_id)

    async def deliver(self, delivery_id: UUID) -> WebhookDelivery:
        delivery = await self.db.scalar(
            select(WebhookDelivery).where(WebhookDelivery.id == delivery_id).with_for_update()
        )
        if not delivery:
            raise NotFoundError("Доставка вебхука не найдена")
        if delivery.success:
            return delivery
        webhook = await self.db.get(Webhook, delivery.webhook_id)
        delivery.attempts += 1
        delivery.delivered_at = datetime.now(UTC)
        delivery.next_attempt_at = None
        owned_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=10, follow_redirects=False)
        try:
            if not webhook or not webhook.is_active:
                raise WebhookDeliveryError("Webhook отключён или удалён")
            pinned_ip = await validate_resolved_target(
                webhook.url, allow_private=self.settings.webhook_allow_private_urls
            )
            body = canonical_payload(delivery.payload)
            secret = decrypt_secret(webhook.secret, self.settings.app_secret_key)
            headers = {
                "X-Webhook-Signature": self._sign_payload(delivery.payload, secret),
                "X-Webhook-Event": delivery.event_type,
                "X-Webhook-Id": str(delivery.event_id),
                "Content-Type": "application/json",
                "User-Agent": "Premium-B2B-Mailer-Webhooks/1.0",
            }
            if self.client is None and not self.settings.webhook_allow_private_urls:
                await client.aclose()
                client = httpx.AsyncClient(
                    transport=PinnedAsyncHTTPTransport(
                        urlparse(webhook.url).hostname or "", pinned_ip
                    ),
                    timeout=10,
                    follow_redirects=False,
                )
            response = await client.post(
                webhook.url, content=body, headers=headers, follow_redirects=False
            )
            delivery.response_status = response.status_code
            delivery.response_body = response.text[:1000]
            delivery.success = 200 <= response.status_code < 300
            delivery.last_error = None if delivery.success else f"HTTP {response.status_code}"
            if not delivery.success:
                delivery.next_attempt_at = datetime.now(UTC) + timedelta(
                    seconds=min(300, 2**delivery.attempts)
                )
                raise WebhookDeliveryError(delivery.last_error)
        except Exception as exc:
            delivery.success = False
            delivery.last_error = str(exc)[:1000]
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 2**delivery.attempts)
            )
            if isinstance(exc, WebhookDeliveryError):
                raise
            raise WebhookDeliveryError(str(exc)) from exc
        finally:
            await self.db.flush()
            if owned_client:
                await client.aclose()
        return delivery
