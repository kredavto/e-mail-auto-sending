from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pyotp
import pytest

from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import create_refresh_token
from app.modules.auth.models import AuthSession
from app.modules.auth.schemas import LoginRequest, MFALoginRequest, RegisterRequest, TokenPair
from app.modules.auth.service import AuthService
from app.modules.users.models import User


def user(**changes: object) -> User:
    values: dict[str, object] = {
        "id": uuid4(),
        "email": "owner@example.com",
        "password_hash": "$2b$12$2zTHUS6v6ksTRKQJdgg6duT4TA4qCMNB1fG30diRtg5SnWapYtVwC",
        "full_name": "Owner",
        "failed_login_attempts": 0,
        "mfa_enabled": False,
    }
    values.update(changes)
    return User(**values)


def service() -> AuthService:
    instance = AuthService(AsyncMock())
    instance.users = Mock()
    instance.sessions = Mock()
    instance.security_audit = SimpleNamespace(record=AsyncMock())
    return instance


@pytest.mark.asyncio
async def test_register_and_duplicate() -> None:
    auth = service()
    payload = RegisterRequest(email="new@example.com", password="StrongPassword1", full_name="New")
    auth.users.get_by_email = AsyncMock(return_value=None)
    auth.users.add = AsyncMock(side_effect=lambda item: item)
    created = await auth.register(payload)
    assert created.email == "new@example.com"

    auth.users.get_by_email = AsyncMock(return_value=created)
    with pytest.raises(ConflictError):
        await auth.register(payload)


@pytest.mark.asyncio
async def test_login_lockout_and_mfa_requirement(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = service()
    locked_user = user(failed_login_attempts=4)
    auth.users.get_by_email = AsyncMock(return_value=locked_user)
    monkeypatch.setattr("app.modules.auth.service.verify_password", lambda *_: False)
    with pytest.raises(AuthenticationError):
        await auth.login(LoginRequest(email=locked_user.email, password="wrong"), None, None)
    assert locked_user.locked_until is not None

    mfa_user = user(mfa_enabled=True, locked_until=None)
    auth.users.get_by_email = AsyncMock(return_value=mfa_user)
    monkeypatch.setattr("app.modules.auth.service.verify_password", lambda *_: True)
    result = await auth.login(LoginRequest(email=mfa_user.email, password="ok"), None, None)
    assert result.mfa_required


@pytest.mark.asyncio
async def test_login_with_mfa_issues_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = pyotp.random_base32()
    mfa_user = user(mfa_enabled=True, mfa_secret=secret, locked_until=None)
    auth = service()
    auth.users.get_by_email = AsyncMock(return_value=mfa_user)
    auth._issue_pair = AsyncMock(return_value=TokenPair(access_token="a", refresh_token="r"))
    monkeypatch.setattr("app.modules.auth.service.verify_password", lambda *_: True)
    payload = MFALoginRequest(email=mfa_user.email, password="ok", code=pyotp.TOTP(secret).now())
    assert (await auth.login(payload, "127.0.0.1", "tests")).access_token == "a"


@pytest.mark.asyncio
async def test_refresh_rotation_and_reuse() -> None:
    auth = service()
    family_id, user_id, session_id = uuid4(), uuid4(), uuid4()
    token = create_refresh_token(user_id, session_id, family_id)
    auth.sessions.get_by_hash = AsyncMock(return_value=None)
    auth.sessions.revoke_family = AsyncMock()
    with pytest.raises(AuthenticationError):
        await auth.refresh(token)
    auth.sessions.revoke_family.assert_awaited_once_with(family_id)

    row = AuthSession(
        id=session_id,
        user_id=user_id,
        family_id=family_id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    auth.sessions.get_by_hash = AsyncMock(return_value=row)
    auth._issue_pair = AsyncMock(return_value=TokenPair(access_token="a", refresh_token="b"))
    pair = await auth.refresh(token)
    assert pair.refresh_token == "b"
    assert row.rotated_at is not None
    assert row.revoked_at is not None


@pytest.mark.asyncio
async def test_logout_and_mfa_setup_verify() -> None:
    auth = service()
    session = AuthSession(family_id=uuid4())
    auth.sessions.get_by_hash = AsyncMock(return_value=session)
    auth.sessions.revoke_family = AsyncMock()
    await auth.logout("token")
    auth.sessions.revoke_family.assert_awaited_once_with(session.family_id)

    current = user()
    secret, uri = auth.setup_mfa(current)
    assert secret in uri
    await auth.verify_mfa(current, pyotp.TOTP(secret).now())
    assert current.mfa_enabled
