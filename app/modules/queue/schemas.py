from uuid import UUID

from pydantic import BaseModel

from app.shared.dto import ORMModel


class QueueStats(BaseModel):
    queues: dict[str, int]
    workers: int


class FailedTaskResponse(ORMModel):
    id: UUID
    task_name: str
    error: str
    retries: int
    status: str
