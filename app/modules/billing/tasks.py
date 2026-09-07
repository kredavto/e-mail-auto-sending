import asyncio
from datetime import UTC, datetime

from app.celery_app import celery_app


@celery_app.task(name="app.modules.billing.tasks.rollover_billing_periods")  # type: ignore[untyped-decorator]
def rollover_billing_periods() -> dict[str, int]:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.billing.models import Subscription
    from app.modules.billing.service import BillingService

    async def run() -> dict[str, int]:
        changed = 0
        async with async_session_factory() as db:
            rows = list(
                (
                    await db.scalars(
                        select(Subscription).where(
                            Subscription.current_period_end < datetime.now(UTC)
                        )
                    )
                ).all()
            )
            for row in rows:
                if row.cancel_at and row.cancel_at <= datetime.now(UTC):
                    row.status, row.auto_renew = "cancelled", False
                elif row.plan == "free":
                    start, end = BillingService.period_bounds()
                    row.current_period_start, row.current_period_end = start, end
                else:
                    # Paid access never advances on a timer. Only a verified payment callback
                    # can install the next billing period.
                    row.status = "past_due"
                changed += 1
            await db.commit()
        return {"subscriptions_updated": changed}

    return asyncio.run(run())
