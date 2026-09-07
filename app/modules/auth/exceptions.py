from app.core.exceptions import AuthenticationError


class TokenReuseError(AuthenticationError):
    pass
