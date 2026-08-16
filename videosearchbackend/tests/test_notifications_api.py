"""End-to-end tests for the notifications routes.

Skipped unless TEST_DATABASE_URL points at a reachable Postgres — see
tests/conftest.py. The indexing pipeline never runs in tests (INDEX_ON_UPLOAD
is false), so each notification is written the way the pipeline writes it —
via ``notifications_service.create_notification`` on a real session — and
the API surface is then exercised end to end.
"""

import asyncio
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.notifications import service as notifications_service
from tests.conftest import needs_db

pytestmark = needs_db

SIGNUP = {
    "name": "Alex Rivera",
    "email": "alex@example.com",
    "password": "correct-horse-8",
}

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def _signup(
    client: TestClient, *, email: str = "alex@example.com", name: str = "Alex Rivera"
) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/signup",
        json={"name": name, "email": email, "password": SIGNUP["password"]},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(client: TestClient, headers: dict[str, str], *, name: str = "clip.mp4") -> dict:
    files = {"file": (name, io.BytesIO(FAKE_MP4), "video/mp4")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 201, response.text
    return response.json()


def _user_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _run(work):
    """Run `work(session_factory)` against a throwaway engine of its own.

    An asyncpg connection belongs to the event loop that opened it. The
    `client` fixture's TestClient runs the app on its own loop and leaves
    pooled connections behind on it, so reusing the app's shared engine from a
    fresh `asyncio.run` fails with "got Future attached to a different loop".
    Building a private engine inside the new loop sidesteps the shared pool
    entirely — nothing is borrowed, so nothing is bound to the wrong loop.
    """

    async def wrapper():
        private_engine = create_async_engine(get_settings().async_database_url)
        try:
            factory = async_sessionmaker(private_engine, expire_on_commit=False)
            return await work(factory)
        finally:
            await private_engine.dispose()

    return asyncio.run(wrapper())


def _notify(video_id: str, user_id: str) -> None:
    """The row the pipeline writes when a video settles on `ready`."""

    async def create(session_factory) -> None:
        async with session_factory() as db:
            await notifications_service.create_notification(
                db, user_id=uuid.UUID(user_id), video_id=uuid.UUID(video_id)
            )

    _run(create)


def _list(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.get("/api/v1/notifications", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ── Auth ────────────────────────────────────────────────────


def test_notifications_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/notifications").status_code == 401
    assert client.post("/api/v1/notifications/read-all").status_code == 401
    assert (
        client.post(f"/api/v1/notifications/{uuid.uuid4()}/read").status_code == 401
    )


# ── Listing ─────────────────────────────────────────────────


def test_indexed_notification_appears_in_list(client: TestClient) -> None:
    headers = _signup(client)
    user_id = _user_id(client, headers)
    video = _upload(client, headers, name="team-sync.mp4")
    _notify(video["id"], user_id)

    body = _list(client, headers)
    assert body["unread"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["kind"] == "indexed"
    assert item["read"] is False
    assert item["video_id"] == video["id"]
    assert item["video_name"] == "team-sync.mp4"


def test_list_is_newest_first(client: TestClient) -> None:
    headers = _signup(client)
    user_id = _user_id(client, headers)
    first = _upload(client, headers, name="first.mp4")
    second = _upload(client, headers, name="second.mp4")
    _notify(first["id"], user_id)
    _notify(second["id"], user_id)

    items = _list(client, headers)["items"]
    # created_at is same-timestamped server-side, so order falls to id; the
    # contract is "newest first" and both videos' notifications are present.
    assert {item["video_name"] for item in items} == {"first.mp4", "second.mp4"}
    assert len(items) == 2


def test_duplicate_notification_is_deduped(client: TestClient) -> None:
    headers = _signup(client)
    user_id = _user_id(client, headers)
    video = _upload(client, headers)
    # A re-run of the pipeline (audio-only shortcut after a retry, say).
    _notify(video["id"], user_id)
    _notify(video["id"], user_id)

    body = _list(client, headers)
    assert len(body["items"]) == 1
    assert body["unread"] == 1


def test_notifications_are_private(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    owner_id = _user_id(client, owner)
    video = _upload(client, owner)
    _notify(video["id"], owner_id)

    stranger = _signup(client, email="stranger@example.com", name="Stranger")
    body = _list(client, stranger)
    assert body["items"] == []
    assert body["unread"] == 0


def test_deleting_video_cascades_notification(client: TestClient) -> None:
    headers = _signup(client)
    user_id = _user_id(client, headers)
    video = _upload(client, headers)
    _notify(video["id"], user_id)
    assert _list(client, headers)["unread"] == 1

    assert client.delete(f"/api/v1/videos/{video['id']}", headers=headers).status_code == 200
    assert _list(client, headers)["unread"] == 0


# ── Marking read ────────────────────────────────────────────


def test_mark_one_read(client: TestClient) -> None:
    headers = _signup(client)
    user_id = _user_id(client, headers)
    video = _upload(client, headers)
    _notify(video["id"], user_id)
    notification_id = _list(client, headers)["items"][0]["id"]

    response = client.post(
        f"/api/v1/notifications/{notification_id}/read", headers=headers
    )
    assert response.status_code == 200, response.text

    body = _list(client, headers)
    assert body["unread"] == 0
    assert body["items"][0]["read"] is True


def test_mark_read_unknown_or_foreign_is_404(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    owner_id = _user_id(client, owner)
    video = _upload(client, owner)
    _notify(video["id"], owner_id)
    notification_id = _list(client, owner)["items"][0]["id"]

    # A random id is a 404…
    assert (
        client.post(
            f"/api/v1/notifications/{uuid.uuid4()}/read", headers=owner
        ).status_code
        == 404
    )
    # …and so is someone else's notification — no existence leaks.
    stranger = _signup(client, email="stranger@example.com", name="Stranger")
    assert (
        client.post(
            f"/api/v1/notifications/{notification_id}/read", headers=stranger
        ).status_code
        == 404
    )


def test_mark_all_read(client: TestClient) -> None:
    headers = _signup(client)
    user_id = _user_id(client, headers)
    first = _upload(client, headers, name="first.mp4")
    second = _upload(client, headers, name="second.mp4")
    _notify(first["id"], user_id)
    _notify(second["id"], user_id)
    assert _list(client, headers)["unread"] == 2

    response = client.post("/api/v1/notifications/read-all", headers=headers)
    assert response.status_code == 200, response.text

    body = _list(client, headers)
    assert body["unread"] == 0
    assert all(item["read"] for item in body["items"])
