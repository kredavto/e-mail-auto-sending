from __future__ import annotations

import csv
import hashlib
import hmac
import io
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from functools import wraps
from typing import ParamSpec, TypeVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.events import DomainEvent
from app.modules.audit.models import AuditExport, AuditLog, SecurityAuditEvent
from app.modules.audit.repository import AuditLogRepository

SENSITIVE_KEY_PARTS = {
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "credential",
    "privatekey",
    "accesskey",
    "apikey",
    "signature",
    "databaseurl",
    "dsn",
}
P = ParamSpec("P")
R = TypeVar("R")


@dataclass(frozen=True)
class AuditContext:
    workspace_id: UUID
    user_id: UUID | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    old_values: dict[str, object] | None = None


_audit_context: ContextVar[AuditContext | None] = ContextVar("audit_context", default=None)


def set_audit_context(context: AuditContext) -> Token[AuditContext | None]:
    return _audit_context.set(context)


def reset_audit_context(token: Token[AuditContext | None]) -> None:
    _audit_context.reset(token)


def get_audit_context() -> AuditContext | None:
    return _audit_context.get()


def _sensitive_key(key: object) -> bool:
    normalized = "".join(character for character in str(key).casefold() if character.isalnum())
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def sanitize(value: object) -> object:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    elif hasattr(value, "__table__"):
        value = {column.name: getattr(value, column.name) for column in value.__table__.columns}
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if _sensitive_key(key) else sanitize(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item) for item in value]
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return sanitize({key: item for key, item in attributes.items() if not key.startswith("_")})
    return str(value)


class AuditService:
    compliance_critical = True

    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.repo = AuditLogRepository(db, workspace_id)

    async def log(
        self,
        action: str,
        resource_type: str,
        *,
        user_id: UUID | None = None,
        resource_id: UUID | None = None,
        old_values: dict[str, object] | None = None,
        new_values: dict[str, object] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        return await self.repo.create(
            AuditLog(
                workspace_id=self.workspace_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                old_values=sanitize(old_values) if old_values else None,
                new_values=sanitize(new_values) if new_values else None,
                ip_address=ip_address,
                user_agent=(user_agent or "")[:500] or None,
                request_id=request_id,
            )
        )

    async def log_event(self, event: DomainEvent) -> AuditLog:
        return await self.log(
            event.event_type,
            event.resource_type or event.event_type.split(".", 1)[0],
            user_id=event.actor_id,
            resource_id=event.resource_id,
            new_values=event.data,
        )

    async def handle_event(self, event: DomainEvent) -> None:
        await self.log_event(event)

    async def export(self, rows: list[AuditLog], format: str, user_id: UUID) -> tuple[bytes, str]:
        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                ["created_at", "user_id", "action", "resource_type", "resource_id", "ip_address"]
            )
            for row in rows:
                writer.writerow(
                    [
                        row.created_at.isoformat(),
                        row.user_id or "",
                        row.action,
                        row.resource_type,
                        row.resource_id or "",
                        row.ip_address or "",
                    ]
                )
            content = output.getvalue().encode("utf-8-sig")
            media_type = "text/csv; charset=utf-8"
        else:
            lines = ["Premium B2B Mailer - Audit log"] + [
                f"{row.created_at.isoformat()} | {row.action} | "
                f"{row.resource_type} | {row.resource_id or '-'}"
                for row in rows
            ]
            content = _minimal_pdf(lines)
            media_type = "application/pdf"
        self.db.add(
            AuditExport(
                workspace_id=self.workspace_id,
                user_id=user_id,
                format=format,
                filters={},
                checksum=hashlib.sha256(content).hexdigest(),
            )
        )
        await self.db.flush()
        return content, media_type


class SecurityAuditSink:
    """Append a failed-auth event in its own transaction, independent of request rollback."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def record(
        self,
        event_type: str,
        reason: str,
        *,
        email: str | None = None,
        user_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        data: dict[str, object] | None = None,
    ) -> None:
        from app.database import async_session_factory

        email_hash = None
        if email:
            email_hash = hmac.new(
                self.settings.app_secret_key.encode(),
                email.strip().casefold().encode(),
                hashlib.sha256,
            ).hexdigest()
        async with async_session_factory() as db:
            db.add(
                SecurityAuditEvent(
                    event_type=event_type,
                    user_id=user_id,
                    email_hash=email_hash,
                    reason=reason,
                    ip_address=ip_address,
                    user_agent=(user_agent or "")[:500] or None,
                    data=sanitize(data or {}),
                )
            )
            await db.commit()


def audited(
    action: str, resource_type: str | None = None, *, log_result: bool = True
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Audit a successful async service method using request-local tenant context."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            result = await func(*args, **kwargs)
            context = get_audit_context()
            owner = args[0] if args else None
            db = getattr(owner, "db", None) or getattr(getattr(owner, "repo", None), "db", None)
            if context and isinstance(db, AsyncSession):
                resource = result[0] if isinstance(result, tuple) and result else result
                identifier = getattr(resource, "id", None)
                sanitized = sanitize(result) if log_result else None
                new_values = (
                    sanitized
                    if isinstance(sanitized, dict)
                    else ({"result": sanitized} if sanitized is not None else None)
                )
                await AuditService(db, context.workspace_id).log(
                    action,
                    resource_type or action.split(".", 1)[0],
                    user_id=context.user_id,
                    resource_id=identifier if isinstance(identifier, UUID) else None,
                    old_values=context.old_values,
                    new_values=new_values,
                    ip_address=context.ip_address,
                    user_agent=context.user_agent,
                    request_id=context.request_id,
                )
            return result

        return wrapper

    return decorator


def _minimal_pdf(lines: list[str]) -> bytes:
    """Generate a dependency-free, valid one-page PDF for compliance exports."""
    safe = [
        line.encode("ascii", "replace")
        .decode()
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        for line in lines[:55]
    ]
    stream = (
        "BT /F1 9 Tf 36 800 Td " + " ".join(f"({line[:130]}) Tj 0 -13 Td" for line in safe) + " ET"
    )
    objects = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >> endobj\n",
        f"4 0 obj << /Length {len(stream.encode())} >> stream\n{stream}\nendstream endobj\n",
        "5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj.encode())
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(output)
