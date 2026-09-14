"""Authentication routes: signup, login, refresh, logout, me.

Token strategy
--------------
* **Access token** — a 15-minute JWT returned in the response body. The
  client keeps it in memory and sends it as `Authorization: Bearer …`.
* **Refresh token** — an opaque, rotating token in an httpOnly cookie scoped
  to `/api/v1/auth`. JavaScript cannot read it, so an XSS bug cannot steal a
  long-lived session.

When the access token expires the client gets a 401, calls `POST
/auth/refresh` (the cookie rides along automatically) and retries the
original request with the new token.

All of which applies only while `AUTH_ENABLED=true`. With the switch off the
credential endpoints below answer 404 — nothing here is deleted, it is just
unreachable — and `GET /auth/me` reports the browser's own throwaway session
account so a client can still discover who it is running as. That mode adds
one endpoint of its own, `POST /auth/session/reset`, for starting over with an
empty library.
"""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.auth import service as auth_service
from app.auth.deps import CurrentUser, DbSession
from app.auth.guest import clear_session_cookie, new_session_token, set_session_cookie
from app.auth.schemas import (
    LoginRequest,
    MessageResponse,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from app.auth.service import (
    AuthResult,
    EmailAlreadyRegistered,
    InactiveUser,
    InvalidCredentials,
    InvalidRefreshToken,
)
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    # Deliberately identical for "no such email" and "wrong password" so the
    # endpoint cannot be used to discover which accounts exist.
    detail="Email or password is incorrect",
)

_INVALID_REFRESH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Refresh token is missing, expired or already used",
)


def _require_auth_enabled() -> None:
    """Refuse credential endpoints while the app runs in open-access mode.

    404 rather than 403: with `AUTH_ENABLED=false` there is no account system
    to be forbidden by, so the endpoint genuinely does not exist for this
    deployment. The detail line says so, which is what the sign-in form shows
    if a stale client still posts to it.
    """
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Accounts are disabled on this deployment — no sign-up or "
                "sign-in is needed, just upload a video and search it."
            ),
        )


def _set_refresh_cookie(response: Response, result: AuthResult) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=result.refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        expires=int(result.refresh_expires_at.timestamp()),
        path=settings.refresh_cookie_path,
        domain=settings.refresh_cookie_domain,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        domain=settings.refresh_cookie_domain,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def _token_response(result: AuthResult, response: Response) -> TokenResponse:
    _set_refresh_cookie(response, result)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserOut.model_validate(result.user),
    )


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses={409: {"description": "Email already registered"}},
)
async def signup(
    payload: SignupRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> TokenResponse:
    _require_auth_enabled()

    try:
        result = await auth_service.signup(
            db,
            name=payload.name,
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
        )
    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        ) from exc

    return _token_response(result, response)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in",
    responses={401: {"description": "Invalid credentials"}},
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> TokenResponse:
    _require_auth_enabled()

    try:
        result = await auth_service.login(
            db,
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
        )
    except InvalidCredentials as exc:
        raise _INVALID_CREDENTIALS from exc
    except InactiveUser as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled",
        ) from exc

    return _token_response(result, response)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange the refresh cookie for a new access token",
    description=(
        "Called automatically by the client when a request fails with 401. "
        "Rotates the refresh token: the presented one is revoked and replaced."
    ),
    responses={401: {"description": "Missing, expired or reused refresh token"}},
)
async def refresh(
    request: Request,
    response: Response,
    db: DbSession,
) -> TokenResponse:
    _require_auth_enabled()

    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        raise _INVALID_REFRESH

    try:
        result = await auth_service.refresh(
            db,
            raw_token=raw_token,
            user_agent=request.headers.get("user-agent"),
        )
    except InvalidRefreshToken as exc:
        # Drop the dead cookie so the browser stops replaying it.
        _clear_refresh_cookie(response)
        raise _INVALID_REFRESH from exc

    return _token_response(result, response)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Revoke the current session",
)
async def logout(request: Request, response: Response, db: DbSession) -> MessageResponse:
    _require_auth_enabled()

    await auth_service.logout(db, raw_token=request.cookies.get(settings.refresh_cookie_name))
    _clear_refresh_cookie(response)
    return MessageResponse(detail="Signed out")


@router.post(
    "/logout-all",
    response_model=MessageResponse,
    summary="Revoke every session for the signed-in user",
)
async def logout_all(user: CurrentUser, response: Response, db: DbSession) -> MessageResponse:
    _require_auth_enabled()

    await auth_service.revoke_all_for_user(db, user.id)
    await db.commit()
    _clear_refresh_cookie(response)
    return MessageResponse(detail="Signed out of all devices")


@router.get("/me", response_model=UserOut, summary="Current account")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/session/reset",
    response_model=MessageResponse,
    summary="Start a new open-access session",
    description=(
        "Abandons this browser's throwaway session and issues a fresh, empty "
        "one. The previous session's videos are left untouched but become "
        "unreachable — the cookie was the only way back to them. Available "
        "only while accounts are disabled and GUEST_SESSION_MODE=per_browser."
    ),
    responses={404: {"description": "Not running per-browser guest sessions"}},
)
async def reset_session(response: Response) -> MessageResponse:
    """Swap this browser's session cookie for a brand-new one.

    A new token is issued immediately rather than merely clearing the old
    cookie, so the very next request already belongs to the new session — no
    window in which the browser has no identity at all.
    """
    if not settings.guest_sessions_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "This deployment does not use per-browser sessions, so there is nothing to reset."
            ),
        )

    clear_session_cookie(response, settings)
    set_session_cookie(response, new_session_token(), settings)
    return MessageResponse(detail="Started a new session")
