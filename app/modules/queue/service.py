from typing import cast
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.config import get_settings
from app.core.exceptions import NotFoundError
from app.modules.queue.repository import QueueRepository


class QueueService:
    names = ["emails", "tracking", "enrichment", "bitrix", "analytics", "dead_letter"]

    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.repo, self.redis = (
            QueueRepository(db, workspace_id),
            Redis.from_url(get_settings().redis_url),
        )

    async def stats(self) -> dict[str, int]:
        return {name: int(await self.redis.llen(name)) for name in self.names}

    async def retry(self, item_id: UUID) -> None:
        item = await self.repo.get(item_id)
        if not item:
            raise NotFoundError("Задача не найдена")
        args = cast(list[object], item.payload.get("args", []))
        kwargs = cast(dict[str, object], item.payload.get("kwargs", {}))
        celery_app.send_task(item.task_name, args=args, kwargs=kwargs, queue="emails")
        item.retries += 1
        item.status = "retried"
