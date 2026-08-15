"""HTTP auth gate: login required for API and cover files."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import monotonic

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from sonicverse.api.auth_service import user_from_token
from sonicverse.core.auth import AuthUser
from sonicverse.core.database import async_session_maker

# Cover grids fire dozens of /covers requests; skip a DB round-trip per image.
_TOKEN_TTL_SECONDS = 30.0
_TOKEN_CACHE_MAX = 256
_token_user_cache: dict[str, tuple[float, AuthUser]] = {}

_PUBLIC_EXACT = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/status",
    "/api/v1/auth/login",
}

_PUBLIC_PREFIXES = ("/docs", "/redoc", "/assets/")


def extract_token(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token
    cookie = request.cookies.get("sv_token")
    if cookie:
        return cookie.strip() or None
    return None


def is_public(request: Request) -> bool:
    if request.method == "OPTIONS":
        return True
    path = request.url.path
    if path in _PUBLIC_EXACT:
        return True
    if path == "/api/v1/users" and request.method == "POST":
        # First-install bootstrap; service still rejects non-admin after setup.
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


async def resolve_user(token: str) -> AuthUser | None:
    now = monotonic()
    cached = _token_user_cache.get(token)
    if cached is not None and cached[0] > now:
        return cached[1]

    async with async_session_maker() as session:
        user = await user_from_token(session, token)
    if user is None:
        _token_user_cache.pop(token, None)
        return None

    expires = now + _TOKEN_TTL_SECONDS
    _token_user_cache[token] = (expires, user)
    if len(_token_user_cache) > _TOKEN_CACHE_MAX:
        stale = [key for key, (until, _) in _token_user_cache.items() if until <= now]
        for key in stale:
            _token_user_cache.pop(key, None)
        if len(_token_user_cache) > _TOKEN_CACHE_MAX:
            _token_user_cache.clear()
            _token_user_cache[token] = (expires, user)
    return user


class AuthGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        needs_auth = path.startswith("/api/") or path.startswith("/covers/")
        if not needs_auth or is_public(request):
            return await call_next(request)

        token = extract_token(request)
        if not token:
            return JSONResponse({"detail": "未登录"}, status_code=401)

        user = await resolve_user(token)
        if user is None:
            return JSONResponse({"detail": "未登录"}, status_code=401)

        request.state.user = user
        return await call_next(request)
