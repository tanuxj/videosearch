"""Auth dependencies: the request-scoped session and the current user.

Three tiers, matched to the three ways a visitor can arrive:

* `get_current_user` — an account session (bearer token), or open access.
* `get_request_user` — additionally resolves an anonymous visitor to a
  homepage-trial session when `TRIAL_ENABLED` is on. Returns a `RequestUser`
  wrapper whose `is_registered` flag is what product features gate on.
* `require_registered_user` — the gated dependency: everything that costs
  persistence or money (clip download, share links, search history) is
  declared with this instead, so the anonymous homepage demo keeps working
  and the full product stays behind signup.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.guest import resolve_guest_user, resolve_trial_user
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

    return await _resolve_token_user(db, credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(slots=True)
class RequestUser:
    """Who this request acts as, when anonymous visitors are allowed in.

    Wrapping the row (rather than returning `User | None`) keeps the trial
    boundary explicit at every call site: `is_registered` is the one flag
    product features branch on, and `user` is the row all ownership checks
    already take. With `TRIAL_ENABLED` off the flag is always True and every
    gate collapses back to plain auth-required behaviour.
    """

    user: User
    is_registered: bool


async def get_request_user(
    db: DbSession,
    request: Request,
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> RequestUser:
    """Resolve this request to an account, a trial session, or 401.

    A valid bearer token wins: signing in mid-trial moves the browser into
    its real account, and the gate flags flip to registered for that request
    without waiting on any cookie dance. Only a request with no usable
    token — and `trial_sessions_enabled` on — falls through to a trial
    session; a malformed token is still a hard 401 rather than a silent
    downgrade to anonymous, so an expired session surfaces as an error the
    client's refresh flow understands.
    """
    if credentials is not None and credentials.credentials:
        user = await _resolve_token_user(db, credentials.credentials)
        return RequestUser(user=user, is_registered=True)

    if settings.trial_sessions_enabled:
        guest = await resolve_trial_user(db, request, response)
        return RequestUser(user=guest, is_registered=False)

    raise _UNAUTHENTICATED


RequestUserDep = Annotated[RequestUser, Depends(get_request_user)]


async def _resolve_token_user(db: AsyncSession, token: str) -> User:
    """Shared bearer-token resolution for both account dependencies."""
    try:
        user_id = decode_access_token(token)
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


async def require_registered_user(
    request_user: RequestUserDep,
) -> RequestUser:
    """Gate: only an account session may proceed (401 for anonymous visitors).

    This is the product boundary — the dependency every persistent/monetised
    route declares. 401 (not 403) keeps the client's semantics clean: there
    is no signed-in identity here at all, and `401` is what triggers the
    frontend's login/signup prompt rather than a permissions error.
    """
    if not request_user.is_registered:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Create an account to use this feature",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return request_user


RegisteredUser = Annotated[RequestUser, Depends(require_registered_user)]
