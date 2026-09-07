from uuid import uuid4

from app.core.security import create_access_token, decode_token, hash_password, verify_password


def test_password_hash_is_salted() -> None:
    first = hash_password("StrongPassword1")
    second = hash_password("StrongPassword1")
    assert first != second
    assert verify_password("StrongPassword1", first)
    assert not verify_password("WrongPassword1", first)


def test_access_token_claims() -> None:
    user_id, session_id = uuid4(), uuid4()
    claims = decode_token(create_access_token(user_id, session_id), "access")
    assert claims["sub"] == str(user_id)
    assert claims["sid"] == str(session_id)
