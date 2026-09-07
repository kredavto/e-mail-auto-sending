from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class LoginRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.redis = Redis.from_url(get_settings().redis_url)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path.endswith("/auth/login") and request.method == "POST":
            ip = request.client.host if request.client else "unknown"
            key = f"rate:login:{ip}"
            attempts = await self.redis.incr(key)
            if attempts == 1:
                await self.redis.expire(key, 60)
            if attempts > 5:
                return Response("Too many login attempts", status_code=429)
        return await call_next(request)


class AuditContextMiddleware(BaseHTTPMiddleware):
    """Prevents request-local audit metadata leaking into a reused async task context."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        from app.modules.audit.service import _audit_context

        token = _audit_context.set(None)
        try:
            return await call_next(request)
        finally:
            _audit_context.reset(token)
