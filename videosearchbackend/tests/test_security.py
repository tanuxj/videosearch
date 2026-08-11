"""Unit tests for the auth primitives — no database required."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth import security
from app.core.config import get_settings

settings = get_settings()


def test_password_round_trip() -> None:
    digest = security.hash_password("correct-horse-8")
    assert digest.startswith("$argon2id$")
    assert security.verify_password(digest, "correct-horse-8")


def test_wrong_password_is_rejected_without_raising() -> None:
    digest = security.hash_password("correct-horse-8")
    assert security.verify_password(digest, "not-the-password") is False


def test_verify_tolerates_a_corrupt_digest() -> None:
    assert security.verify_password("not-a-hash", "whatever") is False


def test_same_password_yields_different_digests() -> None:
    """Distinct salts, so identical passwords are not linkable in the table."""
    assert security.hash_password("same-pass-1") != security.hash_password("same-pass-1")


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token, expires_in = security.create_access_token(user_id)

    assert expires_in == settings.access_token_ttl_minutes * 60
    assert security.decode_access_token(token) == user_id


def test_access_token_expires_after_the_configured_ttl() -> None:
    token, expires_in = security.create_access_token(uuid.uuid4())
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    lifetime = payload["exp"] - payload["iat"]
    assert lifetime == expires_in == 15 * 60  # the 15-minute default


def test_expired_access_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(seconds=30)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": security.ACCESS_TOKEN_TYPE,
            "iat": int((past - timedelta(minutes=15)).timestamp()),
            "exp": int(past.timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(security.InvalidAccessToken):
        security.decode_access_token(token)


def test_token_signed_with_another_secret_is_rejected() -> None:
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": security.ACCESS_TOKEN_TYPE,
            "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        },
        "a-different-secret",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(security.InvalidAccessToken):
        security.decode_access_token(token)


def test_non_access_token_type_is_rejected() -> None:
    """Guards against a refresh-style token being replayed as a bearer token."""
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "refresh",
            "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(security.InvalidAccessToken):
        security.decode_access_token(token)


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(security.InvalidAccessToken):
        security.decode_access_token("not.a.jwt")


def test_refresh_tokens_are_unique_and_hashed() -> None:
    raw_a, hash_a = security.generate_refresh_token()
    raw_b, hash_b = security.generate_refresh_token()

    assert raw_a != raw_b
    assert hash_a != hash_b
    assert len(hash_a) == 64  # sha256 hex
    assert raw_a not in hash_a  # the raw value is never recoverable from it
    assert security.hash_refresh_token(raw_a) == hash_a


def test_refresh_expiry_uses_the_configured_window() -> None:
    delta = security.refresh_expiry() - datetime.now(UTC)
    assert abs(delta.days - settings.refresh_token_ttl_days) <= 1
