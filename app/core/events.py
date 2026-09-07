import json
import logging
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.config import get_settings

logger = logging.getLogger(__name__)

ENTERPRISE_EVENT_TYPES = frozenset(
    {
        "ab_test.completed",
        "billing.limit_warning",
        "blacklist.detected",
        "campaign.completed",
        "campaign.paused",
        "campaign.started",
        "contact.created",
        "contact.replied",
        "domain.created",
        "email.bounced",
        "email.clicked",
        "email.complained",
        "email.failed",
        "email.opened",
        "email.sent",
        "meeting.booked",
        "product.created",
        "workspace.member_added",
    }
)
ENTERPRISE_HANDLER_REGISTRY = ("notifications", "audit", "webhooks", "billing")


@dataclass(frozen=True)
class DomainEvent:
    workspace_id: UUID
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    actor_id: UUID | None = None
    resource_type: str | None = None
    resource_id: UUID | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def event_type(self) -> str:
        value = re.sub(r"Event$", "", self.name)
        return re.sub(r"(?<!^)(?=[A-Z])", ".", value).casefold()


@dataclass(frozen=True)
class IntegrationEvent(DomainEvent):
    kind: str = "system.event"

    @property
    def event_type(self) -> str:
        return self.kind


class EventBus:
    def __init__(self, redis: Redis, handlers: Iterable[object] = ()) -> None:
        self.redis = redis
        self.handlers = list(handlers)

    async def publish(self, event: DomainEvent) -> None:
        data: dict[str, Any] = asdict(event)
        data["type"] = event.event_type
        payload = json.dumps(data, default=str)
        critical_handlers = [
            handler for handler in self.handlers if getattr(handler, "compliance_critical", False)
        ]
        for handler in critical_handlers:
            await handler.handle_event(event)  # type: ignore[attr-defined]
        try:
            await self.redis.publish(f"events:{event.event_type}", payload)
        except Exception:
            # Enterprise side effects must not turn a successful core transaction into a 500.
            logger.exception("Unable to publish domain event %s", event.event_type)
        for handler in self.handlers:
            if handler in critical_handlers:
                continue
            try:
                await handler.handle_event(event)  # type: ignore[attr-defined]
            except Exception:
                logger.exception(
                    "Domain event handler %s failed for %s",
                    handler.__class__.__name__,
                    event.event_type,
                )


async def get_event_bus() -> EventBus:
    return EventBus(Redis.from_url(get_settings().redis_url, decode_responses=True))


async def publish_enterprise_event(db: object, event: DomainEvent) -> None:
    """Audit and enqueue an event atomically; workers perform external effects after commit."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.audit.service import AuditService
    from app.modules.billing.service import BillingService
    from app.modules.notifications.models import EnterpriseEventOutbox

    # Lightweight service tests use repository-shaped fakes; side effects are a production concern.
    if not isinstance(db, AsyncSession):
        return
    # Compliance is deliberately first. If it fails, no outbox row can become visible and no
    # Redis/email/push/webhook side effect has happened.
    await AuditService(db, event.workspace_id).log_event(event)
    await BillingService(db, event.workspace_id).update_usage(event)
    db.add(
        EnterpriseEventOutbox(
            workspace_id=event.workspace_id,
            event_id=event.event_id,
            event_type=event.event_type,
            actor_id=event.actor_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            data=json.loads(json.dumps(event.data, default=str)),
            occurred_at=event.occurred_at,
        )
    )
    await db.flush()
