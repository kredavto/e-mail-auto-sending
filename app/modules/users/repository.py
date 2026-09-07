from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User, Workspace, WorkspaceInvitation, WorkspaceMember


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.scalars(select(User).where(User.email == email))
        return result.first()

    async def get(self, user_id: UUID) -> User | None:
        return await self.db.get(User, user_id)

    async def add(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        return user


class WorkspaceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, workspace: Workspace, member: WorkspaceMember) -> Workspace:
        self.db.add_all([workspace, member])
        await self.db.flush()
        return workspace

    async def list_for_user(self, user_id: UUID) -> list[Workspace]:
        query = select(Workspace).join(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
        return list((await self.db.scalars(query)).all())

    async def membership(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMember | None:
        result = await self.db.scalars(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
            )
        )
        return result.first()

    async def invite(self, invitation: WorkspaceInvitation) -> WorkspaceInvitation:
        self.db.add(invitation)
        await self.db.flush()
        return invitation

    async def invitation_by_hash(self, digest: str) -> WorkspaceInvitation | None:
        result = await self.db.scalars(
            select(WorkspaceInvitation)
            .where(WorkspaceInvitation.token_hash == digest)
            .with_for_update()
        )
        return result.first()

    async def add_member(self, member: WorkspaceMember) -> WorkspaceMember:
        self.db.add(member)
        await self.db.flush()
        return member

    async def members(self, workspace_id: UUID) -> list[tuple[WorkspaceMember, User]]:
        rows = await self.db.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )
        return list(rows.tuples().all())
