"""End-to-end tests for the auth routes.

Skipped unless TEST_DATABASE_URL points at a reachable Postgres — see
tests/conftest.py.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import security
from app.core.config import get_settings
from tests.conftest import needs_db

pytestmark = needs_db

settings = get_settings()

SIGNUP = {"name": "Alex Rivera", "email": "alex@example.com", "password": "correct-horse-8"}


def _signup(client: TestClient, **overrides: object) -> dict:
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


# ── Signup ──────────────────────────────────────────────────────


def test_signup_returns_access_token_and_user(client: TestClient) -> None:
    body = _signup(client)

    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    assert body["user"]["email"] == "alex@example.com"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_signup_never_returns_the_refresh_token_in_the_body(client: TestClient) -> None:
    response = client.post("/api/v1/auth/signup", json=SIGNUP)
    assert "refresh" not in response.text.lower()


def test_signup_sets_an_httponly_path_scoped_cookie(client: TestClient) -> None:
    response = client.post("/api/v1/auth/signup", json=SIGNUP)
    header = response.headers["set-cookie"]

    assert settings.refresh_cookie_name in header
    assert "HttpOnly" in header
    assert f"Path={settings.refresh_cookie_path}" in header
    assert "SameSite=lax" in header.replace("samesite", "SameSite")


def test_signup_normalises_the_email(client: TestClient) -> None:
    body = _signup(client, email="  ALEX@Example.COM  ")
    assert body["user"]["email"] == "alex@example.com"


def test_duplicate_email_is_rejected_case_insensitively(client: TestClient) -> None:
    _signup(client)
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, "email": "ALEX@EXAMPLE.COM"})
    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "short"},
        {"email": "not-an-email"},
        {"name": "A"},
    ],
)
def test_signup_validates_input(client: TestClient, payload: dict) -> None:
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, **payload})
    assert response.status_code == 422


# ── Login ───────────────────────────────────────────────────────


def test_login_succeeds_with_correct_credentials(client: TestClient) -> None:
    _signup(client)
    client.cookies.clear()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": SIGNUP["password"]},
    )
    assert response.status_code == 200
    assert response.json()["user"]["name"] == "Alex Rivera"


def test_login_with_wrong_password_is_401(client: TestClient) -> None:
    _signup(client)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_login_does_not_reveal_whether_an_account_exists(client: TestClient) -> None:
    _signup(client)

    known = client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": "wrong-password"},
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password"},
    )

    assert known.status_code == unknown.status_code == 401
    assert known.json()["detail"] == unknown.json()["detail"]


# ── Protected route ─────────────────────────────────────────────


def test_me_returns_the_signed_in_account(client: TestClient) -> None:
    token = _signup(client)["access_token"]
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "alex@example.com"


def test_me_without_a_token_is_401(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_with_an_expired_token_is_401(client: TestClient) -> None:
    """This 401 is what makes the client call /auth/refresh."""
    body = _signup(client)
    past = datetime.now(UTC) - timedelta(seconds=5)
    expired = jwt.encode(
        {
            "sub": body["user"]["id"],
            "type": security.ACCESS_TOKEN_TYPE,
            "iat": int((past - timedelta(minutes=15)).timestamp()),
            "exp": int(past.timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_me_with_a_token_for_a_deleted_user_is_401(client: TestClient) -> None:
    token, _ = security.create_access_token(uuid.uuid4())
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# ── Refresh rotation ────────────────────────────────────────────


def test_refresh_issues_a_new_token_pair(client: TestClient) -> None:
    first = _signup(client)
    original_cookie = client.cookies[settings.refresh_cookie_name]

    response = client.post("/api/v1/auth/refresh")
    assert response.status_code == 200

    body = response.json()
    assert body["expires_in"] == 15 * 60
    assert body["user"]["email"] == first["user"]["email"]
    # The refresh token must rotate, not be handed back unchanged.
    assert client.cookies[settings.refresh_cookie_name] != original_cookie


def test_refreshed_access_token_works(client: TestClient) -> None:
    _signup(client)
    token = client.post("/api/v1/auth/refresh").json()["access_token"]

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_refresh_without_a_cookie_is_401(client: TestClient) -> None:
    client.cookies.clear()
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_replaying_a_rotated_token_kills_every_session(client: TestClient) -> None:
    """Reuse means the token leaked, so the whole family is revoked."""
    _signup(client)
    stale = client.cookies[settings.refresh_cookie_name]

    assert client.post("/api/v1/auth/refresh").status_code == 200
    current = client.cookies[settings.refresh_cookie_name]

    # Replay the rotated-out token.
    client.cookies.set(settings.refresh_cookie_name, stale, path=settings.refresh_cookie_path)
    assert client.post("/api/v1/auth/refresh").status_code == 401

    # The legitimate token is now dead too.
    client.cookies.set(settings.refresh_cookie_name, current, path=settings.refresh_cookie_path)
    assert client.post("/api/v1/auth/refresh").status_code == 401


# ── Logout ──────────────────────────────────────────────────────


def test_logout_revokes_the_session(client: TestClient) -> None:
    _signup(client)
    cookie = client.cookies[settings.refresh_cookie_name]

    assert client.post("/api/v1/auth/logout").status_code == 200

    client.cookies.set(settings.refresh_cookie_name, cookie, path=settings.refresh_cookie_path)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_without_a_session_still_succeeds(client: TestClient) -> None:
    client.cookies.clear()
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_logout_all_revokes_other_devices(client: TestClient) -> None:
    body = _signup(client)
    device_one = client.cookies[settings.refresh_cookie_name]

    # A second sign-in stands in for a second device.
    client.cookies.clear()
    client.post(
        "/api/v1/auth/login",
        json={"email": SIGNUP["email"], "password": SIGNUP["password"]},
    )

    response = client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert response.status_code == 200

    client.cookies.set(settings.refresh_cookie_name, device_one, path=settings.refresh_cookie_path)
    assert client.post("/api/v1/auth/refresh").status_code == 401
