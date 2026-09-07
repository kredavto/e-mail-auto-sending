from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol
from uuid import UUID

import aiosmtplib
import httpx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.events import DomainEvent
from app.core.exceptions import NotFoundError
from app.modules.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    WebPushSubscription,
)
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import PreferenceUpdate, WebPushSubscriptionCreate
from app.modules.users.models import User, WorkspaceMember

logger = logging.getLogger(__name__)
CRITICAL_TYPES = {"error", "blacklist_detected", "smtp_auth_failed", "complaint"}


class NotificationDeliveryError(Exception):
    pass


class PushSender(Protocol):
    async def send(self, subscription: WebPushSubscription, payload: dict[str, object]) -> None: ...


class WebPushSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send(self, subscription: WebPushSubscription, payload: dict[str, object]) -> None:
        if not self.settings.webpush_vapid_private_key:
            raise NotificationDeliveryError("VAPID private key не настроен")
        try:
            from pywebpush import webpush  # type: ignore[import-not-found]
        except ImportError:
            raise NotificationDeliveryError("pywebpush не установлен") from None

        def deliver() -> None:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=json.dumps(payload, default=str),
                vapid_private_key=self.settings.webpush_vapid_private_key,
                vapid_claims={"sub": self.settings.webpush_vapid_subject},
            )

        import asyncio

        await asyncio.to_thread(deliver)


class NotificationDispatcher:
    """Materializes durable notification jobs and delivers one locked channel row."""

    def __init__(
        self,
        db: AsyncSession,
        redis: Redis | None = None,
        settings: Settings | None = None,
        push_sender: PushSender | None = None,
    ) -> None:
        self.db = db
        self.repo = NotificationRepository(db)
        self.settings = settings or get_settings()
        self.redis = redis
        self.push_sender = push_sender or WebPushSender(self.settings)

    @staticmethod
    def serialize(row: Notification) -> dict[str, object]:
        return {
            "id": str(row.id),
            "workspace_id": str(row.workspace_id),
            "type": row.type,
            "title": row.title,
            "message": row.message,
            "data": row.data,
            "channel": "in_app",
            "is_read": row.is_read,
            "created_at": (
                row.created_at.isoformat() if row.created_at else datetime.now(UTC).isoformat()
            ),
        }

    @staticmethod
    def _enabled(preference: NotificationPreference | None, channel: str, event_type: str) -> bool:
        if channel == "email" and event_type in CRITICAL_TYPES:
            return True
        if not preference:
            return False
        values = getattr(preference, f"{channel}_notifications")
        return bool(values.get(event_type, False))

    async def _publish(self, user_id: UUID, payload: dict[str, object]) -> None:
        redis = self.redis or Redis.from_url(self.settings.redis_url, decode_responses=True)
        owned = self.redis is None
        try:
            await redis.publish(f"user:{user_id}:notifications", json.dumps(payload, default=str))
        except Exception:
            logger.exception("Unable to publish real-time notification for user=%s", user_id)
        finally:
            if owned:
                await redis.aclose()

    async def _send_email(self, row: Notification, delivery_id: UUID) -> None:
        user = await self.db.get(User, row.user_id)
        if not user or not self.settings.smtp_host:
            raise NotificationDeliveryError("SMTP или пользователь уведомления недоступен")
        message = EmailMessage()
        message["From"] = self.settings.notification_from_email
        message["To"] = user.email
        message["Subject"] = row.title
        domain = self.settings.notification_from_email.rsplit("@", 1)[-1]
        message["Message-ID"] = f"<notification-{delivery_id}@{domain}>"
        message.set_content(row.message)
        await aiosmtplib.send(
            message,
            hostname=self.settings.smtp_host,
            port=self.settings.smtp_port,
            username=self.settings.smtp_username or None,
            password=self.settings.smtp_password or None,
            start_tls=self.settings.smtp_use_tls,
            timeout=30,
        )

    async def _send_telegram(
        self,
        row: Notification,
        preference: NotificationPreference | None,
        delivery_id: UUID,
    ) -> None:
        if (
            not preference
            or not preference.telegram_chat_id
            or not self.settings.telegram_bot_token
        ):
            raise NotificationDeliveryError("Telegram channel не настроен")
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                headers={"X-PBM-Delivery-ID": str(delivery_id)},
                json={
                    "chat_id": preference.telegram_chat_id,
                    "text": f"{row.title}\n{row.message}",
                },
            )
            response.raise_for_status()

    async def handle_event(self, event: DomainEvent) -> None:
        await self.enqueue_event(event)

    async def enqueue_event(self, event: DomainEvent) -> list[Notification]:
        """Materialize in-app records and per-channel jobs without external side effects."""
        event_type = event.event_type
        template = EVENT_NOTIFICATIONS.get(event_type)
        if not template:
            return []
        members = list(
            (
                await self.db.scalars(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == event.workspace_id
                    )
                )
            ).all()
        )
        rows: list[Notification] = []
        for member in members:
            row = await self.db.scalar(
                select(Notification).where(
                    Notification.workspace_id == event.workspace_id,
                    Notification.user_id == member.user_id,
                    Notification.event_id == event.event_id,
                )
            )
            if row is None:
                row = await self.repo.create(
                    Notification(
                        user_id=member.user_id,
                        workspace_id=event.workspace_id,
                        event_id=event.event_id,
                        type=template[0],
                        title=template[1],
                        message=str(event.data.get("message") or template[2]),
                        data={**event.data, "event_id": str(event.event_id)},
                    )
                )
            rows.append(row)
            preference = await self.repo.preference(row.user_id, row.workspace_id)
            channels: list[tuple[str, str]] = []
            if self._enabled(preference, "email", row.type):
                channels.append(("email", ""))
            if self._enabled(preference, "webpush", row.type):
                channels.extend(
                    ("webpush", str(subscription.id))
                    for subscription in await self.repo.subscriptions(row.user_id)
                )
            if self._enabled(preference, "telegram", row.type):
                channels.append(("telegram", ""))
            for channel, target_id in channels:
                existing = await self.db.scalar(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == row.id,
                        NotificationDelivery.channel == channel,
                        NotificationDelivery.target_id == target_id,
                    )
                )
                if existing is None:
                    self.db.add(
                        NotificationDelivery(
                            notification_id=row.id,
                            channel=channel,
                            target_id=target_id,
                        )
                    )
        await self.db.flush()
        return rows

    async def publish_realtime(self, rows: list[Notification]) -> None:
        """Best-effort acceleration only; durable in-app rows remain the source of truth."""
        for row in rows:
            await self._publish(row.user_id, self.serialize(row))

    async def deliver_channel(self, delivery_id: UUID) -> NotificationDelivery:
        delivery = await self.db.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.id == delivery_id)
            .with_for_update()
        )
        if delivery is None:
            raise NotFoundError("Доставка уведомления не найдена")
        if delivery.status == "succeeded":
            return delivery
        row = await self.db.get(Notification, delivery.notification_id)
        if row is None:
            raise NotFoundError("Уведомление не найдено")
        delivery.attempts += 1
        delivery.next_attempt_at = None
        try:
            if delivery.channel == "email":
                await self._send_email(row, delivery.id)
            elif delivery.channel == "webpush":
                subscription = await self.db.get(WebPushSubscription, UUID(delivery.target_id))
                if subscription is None or not subscription.is_active:
                    raise NotificationDeliveryError("Web Push subscription недоступна")
                payload = {**self.serialize(row), "delivery_id": str(delivery.id)}
                await self.push_sender.send(subscription, payload)
            elif delivery.channel == "telegram":
                preference = await self.repo.preference(row.user_id, row.workspace_id)
                await self._send_telegram(row, preference, delivery.id)
            else:
                raise NotificationDeliveryError("Неизвестный канал уведомления")
        except Exception as exc:
            delivery.status = "failed"
            delivery.last_error = str(exc)[:1000]
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 2**delivery.attempts)
            )
            await self.db.flush()
            if isinstance(exc, NotificationDeliveryError):
                raise
            raise NotificationDeliveryError(str(exc)) from exc
        delivery.status = "succeeded"
        delivery.delivered_at = datetime.now(UTC)
        delivery.last_error = None
        await self.db.flush()
        return delivery


EVENT_NOTIFICATIONS: dict[str, tuple[str, str, str]] = {
    "campaign.started": ("campaign_started", "Кампания запущена", "Рассылка началась"),
    "campaign.paused": ("campaign_stopped", "Кампания остановлена", "Рассылка приостановлена"),
    "campaign.completed": ("campaign_completed", "Кампания завершена", "Рассылка завершена"),
    "contact.replied": ("new_reply", "Новый ответ", "Контакт ответил на письмо"),
    "email.bounced": ("bounce", "Письмо не доставлено", "Получен bounce"),
    "email.complained": ("complaint", "Жалоба на письмо", "Получена complaint-жалоба"),
    "ab_test.completed": (
        "ab_test_completed",
        "A/B-тест завершён",
        "Определён результат A/B-теста",
    ),
    "email.failed": ("error", "Ошибка отправки", "Не удалось отправить письмо"),
    "meeting.booked": ("meeting_booked", "Встреча назначена", "Контакт назначил встречу"),
    "billing.limit_warning": (
        "limit_warning",
        "Лимит заканчивается",
        "Использовано более 80% лимита",
    ),
    "blacklist.detected": ("blacklist_detected", "Домен в блэклисте", "Обнаружена DNSBL-запись"),
}


class NotificationService:
    def __init__(self, db: AsyncSession, workspace_id: UUID, user_id: UUID) -> None:
        self.db, self.workspace_id, self.user_id = db, workspace_id, user_id
        self.repo = NotificationRepository(db)

    async def mark_read(self, notification_id: UUID) -> Notification:
        row = await self.repo.get_for_user(notification_id, self.user_id, self.workspace_id)
        if not row:
            raise NotFoundError("Уведомление не найдено")
        row.is_read = True
        row.read_at = datetime.now(UTC)
        await self.db.flush()
        return row

    async def update_preferences(self, data: PreferenceUpdate) -> NotificationPreference:
        row = await self.repo.preference(self.user_id, self.workspace_id)
        if not row:
            row = NotificationPreference(user_id=self.user_id, workspace_id=self.workspace_id)
            self.db.add(row)
        for key, value in data.model_dump().items():
            setattr(row, key, value)
        await self.db.flush()
        return row

    async def subscribe_webpush(self, data: WebPushSubscriptionCreate) -> WebPushSubscription:
        endpoint = str(data.endpoint)
        row = await self.db.scalar(
            select(WebPushSubscription).where(WebPushSubscription.endpoint == endpoint)
        )
        if row:
            row.user_id, row.p256dh, row.auth, row.is_active = (
                self.user_id,
                data.p256dh,
                data.auth,
                True,
            )
        else:
            row = WebPushSubscription(
                user_id=self.user_id, endpoint=endpoint, p256dh=data.p256dh, auth=data.auth
            )
            self.db.add(row)
        await self.db.flush()
        return row
