from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.modules.users.models import User
from app.modules.users.repository import WorkspaceRepository
from app.modules.users.schemas import (
    InvitationAccept,
    InvitationCreate,
    InvitationResponse,
    MemberResponse,
    ProfileUpdate,
    UserResponse,
    WorkspaceCreate,
    WorkspaceResponse,
)
from app.modules.users.service import WorkspaceService
from app.shared.dto import MessageResponse

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
profile_router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    data: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    return WorkspaceResponse.model_validate(await WorkspaceService(db).create(user, data))


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[WorkspaceResponse]:
    items = await WorkspaceRepository(db).list_for_user(user.id)
    return [WorkspaceResponse.model_validate(item) for item in items]


@router.post("/{workspace_id}/invite", response_model=InvitationResponse, status_code=201)
async def invite_member(
    workspace_id: UUID,
    data: InvitationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    return InvitationResponse.model_validate(
        await WorkspaceService(db).invite(workspace_id, user, data)
    )


@router.post("/invitations/accept", response_model=MessageResponse)
async def accept_invitation(
    data: InvitationAccept,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await WorkspaceService(db).accept_invitation(user, data.token)
    return MessageResponse(message="Приглашение принято")


@router.get("/{workspace_id}/members", response_model=list[MemberResponse])
async def members(
    workspace_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    return await WorkspaceService(db).list_members(workspace_id, user)


@profile_router.get("/me", response_model=UserResponse)
async def profile(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@profile_router.patch("/me", response_model=UserResponse)
async def update_profile(
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user.full_name = data.full_name
    await db.flush()
    return UserResponse.model_validate(user)
