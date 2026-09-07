from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import (
    LoginRequest,
    MFALoginRequest,
    MFASetupResponse,
    MFAVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    ResetRequest,
    SessionResponse,
    TokenPair,
)
from app.modules.auth.service import AuthService
from app.modules.users.models import User
from app.modules.users.schemas import UserResponse
from app.shared.dto import MessageResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserResponse:
    return UserResponse.model_validate(await AuthService(db).register(data))


def request_meta(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None, request.headers.get("user-agent"))


@router.post("/login", response_model=TokenPair)
async def login(
    data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenPair:
    return await AuthService(db).login(data, *request_meta(request))


@router.post("/login/mfa", response_model=TokenPair)
async def login_mfa(
    data: MFALoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenPair:
    return await AuthService(db).login(data, *request_meta(request))


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    return await AuthService(db).refresh(data.refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    data: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    await AuthService(db).logout(data.refresh_token, *request_meta(request))
    return Response(status_code=204)


@router.post("/password/reset-request", response_model=MessageResponse)
async def reset_request(_data: ResetRequest) -> MessageResponse:
    return MessageResponse(message="Если адрес существует, инструкция отправлена")


@router.post("/mfa/setup", response_model=MFASetupResponse)
async def mfa_setup(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MFASetupResponse:
    service = AuthService(db)
    secret, uri = service.setup_mfa(user)
    await service.audit_user_action(
        user.id,
        "auth.mfa_setup_requested",
        ip_address=request_meta(request)[0],
        user_agent=request_meta(request)[1],
    )
    return MFASetupResponse(secret=secret, provisioning_uri=uri)


@router.post("/mfa/verify", response_model=MessageResponse)
async def mfa_verify(
    data: MFAVerifyRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await AuthService(db).verify_mfa(user, data.code, *request_meta(request))
    return MessageResponse(message="2FA включена")


@router.get("/sessions", response_model=list[SessionResponse])
async def sessions(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[SessionResponse]:
    return [
        SessionResponse.model_validate(item, from_attributes=True)
        for item in await AuthRepository(db).list_active(user.id)
    ]
