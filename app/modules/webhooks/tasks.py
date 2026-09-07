import asyncio
from uuid import UUID

from app.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    max_retries=4,
    queue="webhooks",
    name="app.modules.webhooks.tasks.deliver_webhook",
)
def deliver_webhook(self: object, delivery_id: str) -> dict[str, object]:
    from app.database import async_session_factory
    from app.modules.webhooks.models import Webhook, WebhookDelivery
    from app.modules.webhooks.service import WebhookDeliveryError, WebhookDispatcher

    async def run() -> dict[str, object]:
        async with async_session_factory() as db:
            delivery = await db.get(WebhookDelivery, UUID(delivery_id))
            if not delivery:
                return {
                    "delivery_id": delivery_id,
                    "status": "retry",
                    "error": "delivery is not committed yet",
                }
            webhook = await db.get(Webhook, delivery.webhook_id)
            if not webhook:
                return {"delivery_id": delivery_id, "status": "missing_webhook"}
            try:
                row = await WebhookDispatcher(db, webhook.workspace_id).deliver(delivery.id)
                await db.commit()
                return {
                    "delivery_id": delivery_id,
                    "status": "delivered",
                    "attempts": row.attempts,
                }
            except WebhookDeliveryError as exc:
                final = delivery.attempts >= 5
                if final:
                    delivery.next_attempt_at = None
                await db.commit()
                return {
                    "delivery_id": delivery_id,
                    "status": "failed" if final else "retry",
                    "attempts": delivery.attempts,
                    "error": str(exc),
                }

    result = asyncio.run(run())
    if result["status"] == "retry":
        retries = int(getattr(getattr(self, "request", None), "retries", 0))
        raise self.retry(  # type: ignore[attr-defined]
            exc=WebhookDeliveryError(str(result.get("error", "Webhook delivery failed"))),
            countdown=min(300, 2 ** (retries + 1)),
        )
    return result


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    queue="webhooks",
    name="app.modules.webhooks.tasks.drain_webhook_outbox",
)
def drain_webhook_outbox(self: object, limit: int = 500) -> dict[str, int]:
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.webhooks.models import WebhookOutbox

    async def run() -> dict[str, int]:
        queued = 0
        async with async_session_factory() as db:
            rows = list(
                (
                    await db.scalars(
                        select(WebhookOutbox)
                        .where(WebhookOutbox.dispatched_at.is_(None))
                        .order_by(WebhookOutbox.created_at)
                        .with_for_update(skip_locked=True)
                        .limit(limit)
                    )
                ).all()
            )
            for row in rows:
                celery_app.send_task(
                    "app.modules.webhooks.tasks.deliver_webhook",
                    args=[str(row.delivery_id)],
                    queue="webhooks",
                )
                row.dispatched_at = datetime.now(UTC)
                queued += 1
            await db.commit()
        return {"queued": queued}

    return asyncio.run(run())
