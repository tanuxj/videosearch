"""Auth dependencies: the request-scoped session and the current user."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.guest import resolve_guest_user
from app.auth.models import User
from app.auth.security import InvalidAccessToken, decode_access_token
from app.core.config import get_settings
from app.db.session import get_db

settings = get_settings()

# auto_error=False so a missing header produces our own 401 shape rather
# than FastAPI's 403.
_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")

DbSession = Annotated[AsyncSession, Depends(get_db)]

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    db: DbSession,
    request: Request,
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    """Resolve the bearer token to a live user, or 401.

    An expired token lands here as a 401, which is exactly what the client's
    interceptor watches for before calling `/auth/refresh`.

    With `AUTH_ENABLED=false` there is no token to resolve: the caller is
    identified by their `vs_guest` session cookie instead (or is issued one
    here on their first request), so the whole app works unauthenticated
    without a single route having to know about it. `response` is injected
    purely so that cookie can be set — FastAPI merges it into the real
    response.
    """
    if not settings.auth_enabled:
        return await resolve_guest_user(db, request, response)

    if credentials is None or not credentials.credentials:
        raise _UNAUTHENTICATED

    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidAccessToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc

    user = await auth_service.get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
