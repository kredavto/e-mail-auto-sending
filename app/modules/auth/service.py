from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_digest,
    verify_password,
)
from app.modules.audit.service import AuditService, SecurityAuditSink
from app.modules.auth.models import AuthSession
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, MFALoginRequest, RegisterRequest, TokenPair
from app.modules.users.models import User, WorkspaceMember
from app.modules.users.repository import UserRepository
from app.shared.utils import normalize_email


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.sessions = AuthRepository(db)
        self.security_audit = SecurityAuditSink()

    async def _audit_failure(
        self,
        reason: str,
        *,
        email: str | None = None,
        user_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        event_type = {
            "bad_mfa": "auth.mfa_failed",
            "refresh_reuse": "auth.refresh_reuse",
            "refresh_expired": "auth.refresh_expired",
            "refresh_malformed": "auth.refresh_failed",
            "refresh_invalid": "auth.refresh_failed",
        }.get(reason, "auth.login_failed")
        await self.security_audit.record(
            event_type,
            reason,
            email=email,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def register(self, data: RegisterRequest) -> User:
        email = normalize_email(str(data.email))
        if await self.users.get_by_email(email):
            raise ConflictError("Пользователь с таким email уже существует")
        return await self.users.add(
            User(email=email, password_hash=hash_password(data.password), full_name=data.full_name)
        )

    async def login(
        self, data: LoginRequest, ip_address: str | None, user_agent: str | None
    ) -> TokenPair:
        user = await self.users.get_by_email(normalize_email(str(data.email)))
        now = datetime.now(UTC)
        if not user or (user.locked_until and user.locked_until > now):
            await self._audit_failure(
                "locked" if user else "unknown_user",
                email=str(data.email),
                user_id=user.id if user else None,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise AuthenticationError("Неверные учетные данные или аккаунт заблокирован")
        if not verify_password(data.password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_login_attempts = 0
            await self.db.flush()
            await self.db.commit()
            await self._audit_failure(
                "bad_password",
                email=user.email,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise AuthenticationError("Неверные учетные данные")
        if user.mfa_enabled:
            if not isinstance(data, MFALoginRequest):
                return TokenPair(access_token="", refresh_token="", mfa_required=True)
            if not user.mfa_secret or not pyotp.TOTP(user.mfa_secret).verify(
                data.code, valid_window=1
            ):
                await self._audit_failure(
                    "bad_mfa",
                    email=user.email,
                    user_id=user.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                raise AuthenticationError("Неверный код 2FA")
        user.failed_login_attempts = 0
        user.locked_until = None
        pair = await self._issue_pair(user.id, uuid4(), ip_address, user_agent)
        await self.audit_user_action(
            user.id,
            "auth.login",
            ip_address=ip_address,
            user_agent=user_agent,
            values={"mfa": user.mfa_enabled},
        )
        return pair

    async def _issue_pair(
        self, user_id: UUID, family_id: UUID, ip_address: str | None, user_agent: str | None
    ) -> TokenPair:
        session_id = uuid4()
        refresh = create_refresh_token(user_id, session_id, family_id)
        session = AuthSession(
            id=session_id,
            user_id=user_id,
            family_id=family_id,
            refresh_token_hash=token_digest(refresh),
            expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.sessions.add_session(session)
        return TokenPair(
            access_token=create_access_token(user_id, session.id), refresh_token=refresh
        )

    async def refresh(self, token: str) -> TokenPair:
        try:
            payload = decode_token(token, "refresh")
        except AuthenticationError as exc:
            cause = exc.__cause__
            if isinstance(cause, jwt.ExpiredSignatureError):
                reason = "refresh_expired"
            elif isinstance(cause, jwt.InvalidSignatureError):
                reason = "refresh_invalid"
            elif isinstance(cause, jwt.DecodeError):
                reason = "refresh_malformed"
            else:
                reason = "refresh_invalid"
            await self._audit_failure(reason)
            raise
        try:
            family_id = UUID(payload["family"])
            user_id = UUID(payload["sub"])
        except (KeyError, TypeError, ValueError) as exc:
            await self._audit_failure("refresh_invalid")
            raise AuthenticationError("Некорректные claims refresh token") from exc
        session = await self.sessions.get_by_hash(token_digest(token))
        if not session or session.revoked_at or session.rotated_at:
            await self.sessions.revoke_family(family_id)
            await self.db.commit()
            await self._audit_failure("refresh_reuse", user_id=user_id)
            raise AuthenticationError("Обнаружено повторное использование refresh token")
        if session.expires_at <= datetime.now(UTC):
            await self._audit_failure("refresh_expired", user_id=session.user_id)
            raise AuthenticationError("Refresh token истек")
        session.rotated_at = datetime.now(UTC)
        pair = await self._issue_pair(
            session.user_id, family_id, session.ip_address, session.user_agent
        )
        session.revoked_at = datetime.now(UTC)
        return pair

    async def logout(
        self, token: str, ip_address: str | None = None, user_agent: str | None = None
    ) -> None:
        session = await self.sessions.get_by_hash(token_digest(token))
        if session:
            await self.sessions.revoke_family(session.family_id)
            await self.audit_user_action(
                session.user_id,
                "auth.logout",
                ip_address=ip_address or session.ip_address,
                user_agent=user_agent or session.user_agent,
            )

    def setup_mfa(self, user: User) -> tuple[str, str]:
        secret = pyotp.random_base32()
        user.mfa_secret = secret
        uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="Premium B2B Mailer")
        return secret, uri

    async def verify_mfa(
        self,
        user: User,
        code: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        if not user.mfa_secret or not pyotp.TOTP(user.mfa_secret).verify(code, valid_window=1):
            await self._audit_failure(
                "bad_mfa",
                email=user.email,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise AuthenticationError("Неверный код 2FA")
        user.mfa_enabled = True
        await self.db.flush()
        await self.audit_user_action(
            user.id,
            "auth.mfa_enabled",
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def audit_user_action(
        self,
        user_id: UUID,
        action: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        values: dict[str, object] | None = None,
    ) -> None:
        # Unit-level repositories use lightweight mocks. Real request transactions fail closed
        # if a required audit row cannot be persisted.
        if not isinstance(self.db, AsyncSession):
            return
        memberships = list(
            (
                await self.db.scalars(
                    select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
                )
            ).all()
        )
        for membership in memberships:
            await AuditService(self.db, membership.workspace_id).log(
                action,
                "user",
                user_id=user_id,
                resource_id=user_id,
                new_values=values,
                ip_address=ip_address,
                user_agent=user_agent,
            )
