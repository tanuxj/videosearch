"""Identities for open access, when there are no accounts to sign in to.

Two shapes, chosen by `GUEST_SESSION_MODE`:

**per_browser** (default) — a throwaway session per browser, like a
disposable-inbox site. A visitor arrives with no `vs_guest` cookie, so one is
minted: 32 random bytes, httpOnly, and the only thing tying that browser to
its videos. The account behind it is *derived* from the token rather than
looked up in a session table — see `user_id_for_token` — which keeps the whole
feature to one table and no migration. Clearing cookies, opening a private
window or switching browsers starts a fresh, empty session.

**shared** — one account for everybody, so every visitor sees the same
library. Simpler, but there is no privacy between visitors at all.

Either way each request still resolves to a real `User` row, because ownership
is what the videos, clips, history and collections tables are keyed on. No
route has to know which mode is running.
"""

import hashlib
import logging
import secrets
import uuid

from fastapi import Request, Response
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

#: Stable identity of the account used in "shared" mode.
GUEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

#: Not a valid Argon2 digest, so `verify_password` can only ever return False
#: for it — a guest account cannot be logged into even if auth is re-enabled.
UNUSABLE_PASSWORD_HASH = "!open-access-no-password"

#: Domain separation, so the digest below can never collide with any other
#: use of the same token.
_ID_NAMESPACE = b"videosearch:guest-session:v1:"

#: Bytes of entropy in a session token. 32 is 256 bits — far past guessable,
#: which matters because the token *is* the credential.
_TOKEN_BYTES = 32

#: `secrets.token_urlsafe(32)` yields 43 chars; anything wildly off that is
#: not a token we issued, so it is replaced rather than trusted.
_MIN_TOKEN_LEN = 32
_MAX_TOKEN_LEN = 128


def new_session_token() -> str:
    """Mint an opaque session token for a browser that has none."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def looks_like_token(value: str | None) -> bool:
    """Cheap sanity check on a cookie value before it is trusted."""
    return bool(value) and _MIN_TOKEN_LEN <= len(value or "") <= _MAX_TOKEN_LEN


def user_id_for_token(token: str) -> uuid.UUID:
    """Derive a session's account id from its token.

    Deriving rather than storing is what avoids a session table (and a
    migration): the same token always resolves to the same account, and a
    token that was never issued simply names an account that does not exist
    yet. It is one-way — SHA-256 truncated to 128 bits — so learning a
    visitor's user id (they appear in API responses) reveals nothing about
    the cookie needed to act as them.
    """
    digest = hashlib.sha256(_ID_NAMESPACE + token.encode("utf-8")).digest()
    return uuid.UUID(bytes=digest[:16])


def _session_email(user_id: uuid.UUID, settings: Settings) -> str:
    """A unique, valid, obviously-undeliverable address for a session.

    The `users.email` unique index still applies to guest accounts, so each
    session needs its own — built from the account id under a subdomain of the
    configured guest address.
    """
    local, _, domain = settings.guest_user_email.partition("@")
    return f"{local}-{user_id.hex}@sessions.{domain}"


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """(Re)issue the session cookie, extending its life on every request.

    Re-setting it each time makes the 30-day window slide, so a browser that
    keeps using the app keeps its library instead of being cut off on a fixed
    deadline from first visit.
    """
    response.set_cookie(
        key=settings.guest_cookie_name,
        value=token,
        max_age=settings.guest_cookie_ttl_seconds,
        # "/" rather than the auth prefix: the cookie has to be attached to
        # video, thumbnail and caption requests as well, which is exactly what
        # lets a plain <video src> or <track src> work without a token.
        path="/",
        domain=settings.guest_cookie_domain,
        secure=settings.guest_cookie_secure,
        httponly=True,
        samesite=settings.guest_cookie_samesite,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """Drop the session cookie, so the next request starts a new session."""
    response.delete_cookie(
        key=settings.guest_cookie_name,
        path="/",
        domain=settings.guest_cookie_domain,
        secure=settings.guest_cookie_secure,
        httponly=True,
        samesite=settings.guest_cookie_samesite,
    )


async def resolve_guest_user(
    db: AsyncSession,
    request: Request,
    response: Response,
) -> User:
    """Return the account for this request in open-access mode."""
    settings = get_settings()

    if not settings.guest_sessions_enabled:
        return await _get_or_create(
            db,
            user_id=GUEST_USER_ID,
            name=settings.guest_user_name,
            email=settings.guest_user_email,
        )

    token = request.cookies.get(settings.guest_cookie_name)
    if not looks_like_token(token):
        token = new_session_token()
    assert token is not None  # narrowed by looks_like_token / the mint above

    set_session_cookie(response, token, settings)

    user_id = user_id_for_token(token)
    return await _get_or_create(
        db,
        user_id=user_id,
        name=settings.guest_user_name,
        email=_session_email(user_id, settings),
    )


async def _get_or_create(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    name: str,
    email: str,
) -> User:
    """Fetch a guest account, creating it on first use.

    `ON CONFLICT DO NOTHING` covers concurrent first requests from the same
    browser (a page that fires several API calls at once): the losers of the
    insert simply read the row the winner wrote.
    """
    user = await db.get(User, user_id)
    if user is not None:
        return user

    await db.execute(
        pg_insert(User)
        .values(
            id=user_id,
            name=name,
            email=email,
            password_hash=UNUSABLE_PASSWORD_HASH,
            is_active=True,
        )
        .on_conflict_do_nothing()
    )
    try:
        await db.commit()
    except IntegrityError:  # pragma: no cover - covered by DO NOTHING above
        await db.rollback()

    user = await db.get(User, user_id)
    if user is None:
        raise RuntimeError(
            f"Could not create the open-access account for {email!r}: the "
            "address already belongs to another account. Change "
            "GUEST_USER_EMAIL and restart."
        )

    logger.info("New open-access session: %s", user_id)
    return user
