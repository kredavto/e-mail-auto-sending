from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_token
from app.database import get_db
from app.modules.auth.models import AuthSession
from app.modules.users.models import User, WorkspaceMember

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise AuthenticationError("Требуется авторизация")
    payload = decode_token(credentials.credentials, "access")
    user = await db.get(User, UUID(payload["sub"]))
    session = await db.get(AuthSession, UUID(payload["sid"]))
    if not user or not user.is_active or not session or session.revoked_at is not None:
        raise AuthenticationError("Сессия недействительна")
    return user


@dataclass(frozen=True)
class TenantContext:
    workspace_id: UUID
    user: User
    role: str


async def get_tenant_context(
    request: Request,
    x_workspace_id: UUID = Header(alias="X-Workspace-ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    membership = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == x_workspace_id, WorkspaceMember.user_id == user.id
        )
    )
    if not membership:
        raise PermissionDeniedError("Нет доступа к workspace")
    # Imported lazily to keep the core dependency independent from the audit models.
    from app.modules.audit.service import AuditContext, set_audit_context

    set_audit_context(
        AuditContext(
            workspace_id=x_workspace_id,
            user_id=user.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            request_id=request.headers.get("x-request-id"),
        )
    )
    return TenantContext(workspace_id=x_workspace_id, user=user, role=membership.role)
