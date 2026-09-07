from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.config import get_settings

settings = get_settings()
celery_app = Celery("premium_mailer", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    include=[
        "app.modules.sender.tasks",
        "app.modules.scheduler.tasks",
        "app.modules.queue.tasks",
        "app.modules.ses.tasks",
        "app.modules.bitrix24.tasks",
        "app.modules.hunter.tasks",
        "app.modules.linkedin.tasks",
        "app.modules.tenchat.tasks",
        "app.modules.omnichannel.tasks",
        "app.modules.ab_testing.tasks",
        "app.modules.email_validation.tasks",
        "app.modules.enrichment.tasks",
        "app.modules.analytics.tasks",
        "app.modules.domains.tasks",
        "app.modules.warmup.tasks",
        "app.modules.blacklists.tasks",
        "app.modules.notifications.tasks",
        "app.modules.webhooks.tasks",
        "app.modules.billing.tasks",
    ],
    task_queues=(
        Queue(
            "emails",
            Exchange("emails"),
            routing_key="emails",
            queue_arguments={"x-max-priority": 10},
        ),
        Queue("tracking", Exchange("tracking"), routing_key="tracking"),
        Queue("enrichment", Exchange("enrichment"), routing_key="enrichment"),
        Queue("bitrix", Exchange("bitrix"), routing_key="bitrix"),
        Queue("analytics", Exchange("analytics"), routing_key="analytics"),
        Queue("notifications", Exchange("notifications"), routing_key="notifications"),
        Queue("webhooks", Exchange("webhooks"), routing_key="webhooks"),
        Queue("billing", Exchange("billing"), routing_key="billing"),
        Queue("dead_letter", Exchange("dead_letter"), routing_key="dead_letter"),
    ),
    task_default_queue="emails",
    task_routes={
        "app.modules.bitrix24.tasks.*": {"queue": "bitrix"},
        "app.modules.ses.tasks.*": {"queue": "tracking"},
        "app.modules.hunter.tasks.*": {"queue": "enrichment"},
        "app.modules.linkedin.tasks.*": {"queue": "enrichment"},
        "app.modules.tenchat.tasks.*": {"queue": "enrichment"},
        "app.modules.email_validation.tasks.*": {"queue": "enrichment"},
        "app.modules.enrichment.tasks.*": {"queue": "enrichment"},
        "app.modules.ab_testing.tasks.*": {"queue": "analytics"},
        "app.modules.analytics.tasks.*": {"queue": "analytics"},
        "app.modules.domains.tasks.*": {"queue": "analytics"},
        "app.modules.warmup.tasks.*": {"queue": "analytics"},
        "app.modules.blacklists.tasks.*": {"queue": "analytics"},
        "app.modules.notifications.tasks.*": {"queue": "notifications"},
        "app.modules.webhooks.tasks.*": {"queue": "webhooks"},
        "app.modules.billing.tasks.*": {"queue": "billing"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    beat_schedule={
        "schedule-active-campaigns-hourly": {
            "task": "app.modules.scheduler.tasks.schedule_campaigns",
            "schedule": 3600.0,
        },
        "check-bitrix-replies": {
            "task": "app.modules.bitrix24.tasks.check_incoming_replies",
            "schedule": crontab(minute="*/5"),
        },
        "check-tenchat-replies": {
            "task": "app.modules.tenchat.tasks.check_incoming_replies",
            "schedule": crontab(minute="*/10"),
        },
        "update-ab-test-metrics": {
            "task": "app.modules.ab_testing.tasks.update_metrics",
            "schedule": crontab(minute=15),
        },
        "aggregate-daily-analytics": {
            "task": "app.modules.analytics.tasks.aggregate_daily",
            "schedule": crontab(hour=3, minute=0),
        },
        "advance-domain-warmup": {
            "task": "app.modules.warmup.tasks.advance_plans",
            "schedule": crontab(hour=2, minute=30),
        },
        "verify-sending-domains": {
            "task": "app.modules.domains.tasks.verify_all_domains",
            "schedule": crontab(hour="*/6", minute=10),
        },
        "check-blacklists": {
            "task": "app.modules.blacklists.tasks.check_all_domains",
            "schedule": crontab(hour=4, minute=0),
        },
        "rollover-billing-periods": {
            "task": "app.modules.billing.tasks.rollover_billing_periods",
            "schedule": crontab(hour=0, minute=5),
        },
        "drain-webhook-outbox": {
            "task": "app.modules.webhooks.tasks.drain_webhook_outbox",
            "schedule": 2.0,
        },
        "drain-enterprise-event-outbox": {
            "task": "app.modules.notifications.tasks.drain_enterprise_event_outbox",
            "schedule": 2.0,
        },
        "drain-notification-deliveries": {
            "task": "app.modules.notifications.tasks.drain_notification_deliveries",
            "schedule": 2.0,
        },
        "finalize-enterprise-event-outbox": {
            "task": "app.modules.notifications.tasks.finalize_enterprise_event_outbox",
            "schedule": 2.0,
        },
    },
    timezone="Europe/Moscow",
)
celery_app.autodiscover_tasks(
    [
        "app.modules.sender",
        "app.modules.scheduler",
        "app.modules.queue",
        "app.modules.ses",
        "app.modules.bitrix24",
        "app.modules.hunter",
        "app.modules.linkedin",
        "app.modules.tenchat",
        "app.modules.omnichannel",
        "app.modules.ab_testing",
        "app.modules.email_validation",
        "app.modules.enrichment",
        "app.modules.analytics",
        "app.modules.domains",
        "app.modules.warmup",
        "app.modules.blacklists",
        "app.modules.notifications",
        "app.modules.webhooks",
        "app.modules.billing",
    ]
)
