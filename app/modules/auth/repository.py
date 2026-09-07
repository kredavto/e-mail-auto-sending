from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuthSession


class AuthRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_session(self, session: AuthSession) -> AuthSession:
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_by_hash(self, digest: str) -> AuthSession | None:
        result = await self.db.scalars(
            select(AuthSession).where(AuthSession.refresh_token_hash == digest).with_for_update()
        )
        return result.first()

    async def revoke_family(self, family_id: UUID) -> None:
        await self.db.execute(
            update(AuthSession)
            .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    async def list_active(self, user_id: UUID) -> list[AuthSession]:
        result = await self.db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
        )
        return list(result.all())
