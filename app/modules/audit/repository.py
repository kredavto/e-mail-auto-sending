from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.modules.audit.models import AuditLog


class AuditLogRepository:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    async def create(self, row: AuditLog) -> AuditLog:
        self.db.add(row)
        await self.db.flush()
        return row

    def _query(
        self,
        user_id: UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Select[tuple[AuditLog]]:
        query = select(AuditLog).where(AuditLog.workspace_id == self.workspace_id)
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        if action:
            query = query.where(AuditLog.action == action)
        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)
        if date_from:
            query = query.where(AuditLog.created_at >= date_from)
        if date_to:
            query = query.where(AuditLog.created_at <= date_to)
        return query

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        user_id: UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[AuditLog], int]:
        query = self._query(user_id, action, resource_type, date_from, date_to)
        count_query = select(func.count()).select_from(query.subquery())
        total = int(await self.db.scalar(count_query) or 0)
        rows = await self.db.scalars(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(rows.all()), total

    async def get(self, log_id: UUID) -> AuditLog | None:
        return cast(
            AuditLog | None,
            await self.db.scalar(
                select(AuditLog).where(
                    AuditLog.id == log_id, AuditLog.workspace_id == self.workspace_id
                )
            ),
        )
