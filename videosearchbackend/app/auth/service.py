"""Authentication business logic.

Kept free of FastAPI types: these functions raise domain errors and the route
layer decides which HTTP status each one maps to.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import security
from app.auth.models import RefreshToken, User

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Base class for authentication failures."""


class EmailAlreadyRegistered(AuthError):
    pass


class InvalidCredentials(AuthError):
    pass


class InactiveUser(AuthError):
    pass


class InvalidRefreshToken(AuthError):
    pass


@dataclass(slots=True)
class AuthResult:
    """Everything the route layer needs to answer a successful auth call."""

    user: User
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == normalize_email(email)))
    return result.scalar_one_or_none()


async def _issue(db: AsyncSession, user: User, user_agent: str | None) -> AuthResult:
    """Mint an access token plus a fresh refresh token row for `user`."""
    access_token, expires_in = security.create_access_token(user.id)
    raw_refresh, token_hash = security.generate_refresh_token()
    expires_at = security.refresh_expiry()

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=user_agent[:255] if user_agent else None,
        )
    )

    return AuthResult(
        user=user,
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=raw_refresh,
        refresh_expires_at=expires_at,
    )


async def signup(
    db: AsyncSession,
    *,
    name: str,
    email: str,
    password: str,
    user_agent: str | None = None,
) -> AuthResult:
    """Create an account and sign the new user straight in."""
    normalized = normalize_email(email)

    if await get_user_by_email(db, normalized) is not None:
        raise EmailAlreadyRegistered(normalized)

    user = User(
        name=name.strip(),
        email=normalized,
        password_hash=security.hash_password(password),
    )
    db.add(user)

    try:
        # Flush before minting tokens so a duplicate email raised by the
        # unique index is reported as a clean 409, not a 500 at commit time.
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise EmailAlreadyRegistered(normalized) from exc

    result = await _issue(db, user, user_agent)
    await db.commit()
    logger.info("Account created: %s", normalized)
    return result


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
) -> AuthResult:
    """Verify credentials and start a session."""
    user = await get_user_by_email(db, email)

    if user is None:
        # Spend the same time as a real verification would.
        security.dummy_verify()
        raise InvalidCredentials(email)

    if not security.verify_password(user.password_hash, password):
        raise InvalidCredentials(email)

    if not user.is_active:
        raise InactiveUser(email)

    # Transparently upgrade digests when Argon2 parameters move on.
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)

    result = await _issue(db, user, user_agent)
    await db.commit()
    return result


async def refresh(
    db: AsyncSession,
    *,
    raw_token: str,
    user_agent: str | None = None,
) -> AuthResult:
    """Rotate a refresh token and mint a new access token.

    The presented token is revoked and replaced. Presenting an
    already-revoked token means it leaked and was replayed, so every session
    for that user is torn down.
    """
    token_hash = security.hash_refresh_token(raw_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    stored = result.scalar_one_or_none()

    if stored is None:
        raise InvalidRefreshToken("unknown token")

    now = datetime.now(UTC)

    if stored.revoked_at is not None:
        logger.warning(
            "Refresh token reuse detected for user %s — revoking all sessions",
            stored.user_id,
        )
        await revoke_all_for_user(db, stored.user_id)
        await db.commit()
        raise InvalidRefreshToken("token already used")

    if stored.expires_at <= now:
        raise InvalidRefreshToken("token expired")

    user = await get_user_by_id(db, stored.user_id)
    if user is None or not user.is_active:
        raise InvalidRefreshToken("account unavailable")

    stored.revoked_at = now
    issued = await _issue(db, user, user_agent)
    await db.commit()
    return issued


async def logout(db: AsyncSession, *, raw_token: str | None) -> None:
    """Revoke the presented refresh token. Silent when there is nothing to do."""
    if not raw_token:
        return

    token_hash = security.hash_refresh_token(raw_token)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


async def revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Revoke every live refresh token for a user (logout everywhere)."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
