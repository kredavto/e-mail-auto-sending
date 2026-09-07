import asyncio
from datetime import UTC, datetime

from app.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    queue="notifications",
    name="app.modules.notifications.tasks.drain_enterprise_event_outbox",
)
def drain_enterprise_event_outbox(self: object, limit: int = 100) -> dict[str, int]:
    from redis.asyncio import Redis
    from sqlalchemy import select

    from app.config import get_settings
    from app.core.events import IntegrationEvent
    from app.database import async_session_factory
    from app.modules.notifications.models import EnterpriseEventOutbox
    from app.modules.notifications.service import NotificationDispatcher
    from app.modules.webhooks.service import WebhookDispatcher

    async def run() -> dict[str, int]:
        materialized = 0
        for _ in range(limit):
            async with async_session_factory() as db:
                row = await db.scalar(
                    select(EnterpriseEventOutbox)
                    .where(EnterpriseEventOutbox.materialized_at.is_(None))
                    .order_by(EnterpriseEventOutbox.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if not row:
                    break
                event = IntegrationEvent(
                    workspace_id=row.workspace_id,
                    event_id=row.event_id,
                    occurred_at=row.occurred_at,
                    actor_id=row.actor_id,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    data=row.data,
                    kind=row.event_type,
                )
                dispatcher = NotificationDispatcher(db)
                rows = await dispatcher.enqueue_event(event)
                await WebhookDispatcher(db, row.workspace_id).handle_event(event)
                row.attempts += 1
                row.last_error = None
                row.materialized_at = datetime.now(UTC)
                await db.commit()
                materialized += 1

            # Realtime is only an acceleration after durable fan-out is committed. Its
            # availability never determines event completion.
            redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
            try:
                await NotificationDispatcher(db, redis=redis).publish_realtime(rows)
            finally:
                await redis.aclose()
        return {"materialized": materialized}

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    queue="notifications",
    name="app.modules.notifications.tasks.finalize_enterprise_event_outbox",
)
def finalize_enterprise_event_outbox(self: object, limit: int = 100) -> dict[str, int]:
    """Complete only events whose durable notification and webhook jobs all succeeded."""
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.notifications.models import (
        EnterpriseEventOutbox,
        Notification,
        NotificationDelivery,
    )
    from app.modules.webhooks.models import WebhookDelivery

    async def run() -> dict[str, int]:
        completed = 0
        async with async_session_factory() as db:
            rows = list(
                (
                    await db.scalars(
                        select(EnterpriseEventOutbox)
                        .where(
                            EnterpriseEventOutbox.materialized_at.is_not(None),
                            EnterpriseEventOutbox.dispatched_at.is_(None),
                        )
                        .order_by(EnterpriseEventOutbox.created_at)
                        .with_for_update(skip_locked=True)
                        .limit(limit)
                    )
                ).all()
            )
            for row in rows:
                pending_notifications = await db.scalar(
                    select(func.count())
                    .select_from(NotificationDelivery)
                    .join(Notification, Notification.id == NotificationDelivery.notification_id)
                    .where(
                        Notification.event_id == row.event_id,
                        NotificationDelivery.status != "succeeded",
                    )
                )
                pending_webhooks = await db.scalar(
                    select(func.count())
                    .select_from(WebhookDelivery)
                    .where(
                        WebhookDelivery.event_id == row.event_id,
                        WebhookDelivery.success.is_(False),
                    )
                )
                if not pending_notifications and not pending_webhooks:
                    row.dispatched_at = datetime.now(UTC)
                    completed += 1
            await db.commit()
        return {"completed": completed}

    return asyncio.run(run())


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    queue="notifications",
    name="app.modules.notifications.tasks.drain_notification_deliveries",
)
def drain_notification_deliveries(self: object, limit: int = 100) -> dict[str, int]:
    """Retry only unfinished channel rows; external delivery is at-least-once."""
    from sqlalchemy import or_, select

    from app.database import async_session_factory
    from app.modules.notifications.models import NotificationDelivery
    from app.modules.notifications.service import (
        NotificationDeliveryError,
        NotificationDispatcher,
    )

    async def run() -> dict[str, int]:
        succeeded = 0
        failed = 0
        for _ in range(limit):
            async with async_session_factory() as db:
                now = datetime.now(UTC)
                row = await db.scalar(
                    select(NotificationDelivery)
                    .where(
                        NotificationDelivery.status != "succeeded",
                        or_(
                            NotificationDelivery.next_attempt_at.is_(None),
                            NotificationDelivery.next_attempt_at <= now,
                        ),
                    )
                    .order_by(NotificationDelivery.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if row is None:
                    break
                try:
                    await NotificationDispatcher(db).deliver_channel(row.id)
                except NotificationDeliveryError:
                    failed += 1
                else:
                    succeeded += 1
                await db.commit()
        return {"succeeded": succeeded, "failed": failed}

    return asyncio.run(run())
