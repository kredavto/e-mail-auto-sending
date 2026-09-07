import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import IntegrationEvent, publish_enterprise_event
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.core.security import token_digest
from app.modules.users.models import User, Workspace, WorkspaceInvitation, WorkspaceMember
from app.modules.users.repository import WorkspaceRepository
from app.modules.users.schemas import InvitationCreate, MemberResponse, WorkspaceCreate
from app.shared.types import WorkspaceRole
from app.shared.utils import normalize_email


class WorkspaceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = WorkspaceRepository(db)

    async def create(self, user: User, data: WorkspaceCreate) -> Workspace:
        workspace = Workspace(id=uuid4(), name=data.name, slug=data.slug, owner_id=user.id)
        member = WorkspaceMember(
            workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER
        )
        try:
            return await self.repo.add(workspace, member)
        except Exception as exc:
            raise ConflictError("Slug workspace уже используется") from exc

    async def invite(
        self, workspace_id: UUID, actor: User, data: InvitationCreate
    ) -> WorkspaceInvitation:
        membership = await self.repo.membership(workspace_id, actor.id)
        if not membership or membership.role not in {WorkspaceRole.OWNER, WorkspaceRole.ADMIN}:
            raise PermissionDeniedError("Недостаточно прав для приглашения")
        raw_token = secrets.token_urlsafe(32)
        invitation = WorkspaceInvitation(
            workspace_id=workspace_id,
            email=normalize_email(str(data.email)),
            role=data.role,
            token_hash=token_digest(raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        invitation = await self.repo.invite(invitation)
        invitation.invite_token = raw_token  # type: ignore[attr-defined]
        return invitation

    async def list_members(self, workspace_id: UUID, actor: User) -> list[MemberResponse]:
        if not await self.repo.membership(workspace_id, actor.id):
            raise PermissionDeniedError("Нет доступа к workspace")
        return [
            MemberResponse(
                id=member.id,
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=member.role,
            )
            for member, user in await self.repo.members(workspace_id)
        ]

    async def accept_invitation(self, actor: User, raw_token: str) -> WorkspaceMember:
        invitation = await self.repo.invitation_by_hash(token_digest(raw_token))
        now = datetime.now(UTC)
        if (
            not invitation
            or invitation.accepted_at is not None
            or invitation.expires_at <= now
            or invitation.email != actor.email
        ):
            raise PermissionDeniedError("Приглашение недействительно или истекло")
        existing = await self.repo.membership(invitation.workspace_id, actor.id)
        if existing:
            invitation.accepted_at = now
            return existing
        from app.modules.billing.service import BillingService

        await BillingService(self.db, invitation.workspace_id).check_limits("add_user")
        member = await self.repo.add_member(
            WorkspaceMember(
                workspace_id=invitation.workspace_id,
                user_id=actor.id,
                role=invitation.role,
            )
        )
        invitation.accepted_at = now
        await publish_enterprise_event(
            self.db,
            IntegrationEvent(
                workspace_id=invitation.workspace_id,
                actor_id=actor.id,
                resource_type="workspace_member",
                resource_id=member.id,
                data={"email": actor.email},
                kind="workspace.member_added",
            ),
        )
        return member
