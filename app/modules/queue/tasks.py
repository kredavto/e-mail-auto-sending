import asyncio
from typing import Any
from uuid import UUID

from celery import Task


class DeadLetterTask(Task):  # type: ignore[misc]
    """Persists terminal Celery failures for operator-controlled replay."""

    abstract = True

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        einfo: Any,
    ) -> None:
        from app.database import async_session_factory
        from app.modules.queue.models import FailedTask

        async def persist() -> None:
            workspace_id: UUID | None = None
            if args and isinstance(args[0], str):
                try:
                    workspace_id = UUID(args[0])
                except ValueError:
                    pass
            async with async_session_factory() as db:
                db.add(
                    FailedTask(
                        workspace_id=workspace_id,
                        task_name=self.name,
                        payload={"args": list(args), "kwargs": kwargs},
                        error=str(exc),
                        retries=int(self.request.retries),
                    )
                )
                await db.commit()

        asyncio.run(persist())
        super().on_failure(exc, task_id, args, kwargs, einfo)
