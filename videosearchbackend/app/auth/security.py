"""Password hashing and token primitives.

Deliberately split from `services/auth.py`: nothing here touches the
database, so it is trivially unit-testable.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

settings = get_settings()

# Argon2id defaults from argon2-cffi are already OWASP-appropriate.
_hasher = PasswordHasher()

# A real digest of a throwaway secret, used to equalise login timing.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

ACCESS_TOKEN_TYPE = "access"


def hash_password(password: str) -> str:
    """Return an Argon2id digest for `password`."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time-ish verification that never raises on a bad password."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the digest predates the current Argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:  # pragma: no cover - corrupt row
        return True


def dummy_verify() -> None:
    """Burn a hash cycle so a missing account costs the same as a wrong password.

    Without this, an unknown email returns measurably faster than a known one
    and the login endpoint becomes a user-enumeration oracle.
    """
    verify_password(_DUMMY_HASH, "not-the-password")


# ── Access tokens (JWT) ─────────────────────────────────────────


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    """Return `(token, expires_in_seconds)` for a short-lived access token."""
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.access_token_ttl_seconds


class InvalidAccessToken(Exception):
    """Raised when a bearer token is malformed, expired or the wrong type."""


def decode_access_token(token: str) -> uuid.UUID:
    """Validate an access token and return the user id it belongs to."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidAccessToken(str(exc)) from exc

    # A refresh token must never be accepted as a bearer credential.
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidAccessToken("Wrong token type")

    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidAccessToken("Malformed subject") from exc


# ── Refresh tokens (opaque) ─────────────────────────────────────


def generate_refresh_token() -> tuple[str, str]:
    """Return `(raw_token, sha256_digest)`. Only the digest is persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    """SHA-256 hex digest — fast by design, the token is already high-entropy."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_expiry() -> datetime:
    """Absolute expiry for a newly issued refresh token."""
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
