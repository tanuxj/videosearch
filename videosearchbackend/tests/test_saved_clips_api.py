"""End-to-end tests for the saved-clip routes.

Skipped unless TEST_DATABASE_URL points at a reachable Postgres — see
tests/conftest.py. Clips are normally written by the URL-import auto-extract
job, so these tests insert rows through the service directly, then exercise
the list/delete routes and their ownership rules.
"""

import asyncio
import io
import uuid

from fastapi.testclient import TestClient

from app.db.session import SessionFactory, engine
from app.videos.saved_clips import save_clips
from tests.conftest import needs_db

pytestmark = needs_db

SIGNUP = {"name": "Alex Rivera", "email": "alex@example.com", "password": "correct-horse-8"}

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def _run(coro):
    """Run a coroutine in a throwaway loop, then empty the connection pool.

    Mirrors tests/conftest.py: asyncpg connections are bound to the loop that
    created them, so the pool must be disposed before the next `asyncio.run`.
    """

    async def wrapper():
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


def _auth(client: TestClient, **overrides: object) -> tuple[dict[str, str], str]:
    """Sign up and return `(auth headers, user id)`."""
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, **overrides})
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _upload_video(client: TestClient, headers: dict[str, str]) -> str:
    files = {"file": ("clip.mp4", io.BytesIO(FAKE_MP4), "video/mp4")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _save_clip(
    video_id: str,
    owner_id: str,
    *,
    prompt: str = "a red car",
    score: float = 0.81,
) -> str:
    """Insert one saved clip directly, as the auto-extract job would."""

    async def insert() -> str:
        async with SessionFactory() as db:
            rows = await save_clips(
                db,
                owner_id=uuid.UUID(owner_id),
                video_id=uuid.UUID(video_id),
                prompt=prompt,
                clips=[{"start": 0.0, "end": 6.0, "timestamp": 3.0, "score": score}],
            )
            return str(rows[0].id)

    return _run(insert())


# ── Auth ───────────────────────────────────────────────────────


def test_list_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/videos/00000000-0000-0000-0000-000000000000/clips")
    assert response.status_code == 401


# ── List ───────────────────────────────────────────────────────


def test_list_empty_for_video_without_clips(client: TestClient) -> None:
    headers, _ = _auth(client)
    video_id = _upload_video(client, headers)

    body = client.get(f"/api/v1/videos/{video_id}/clips", headers=headers).json()
    assert body["count"] == 0
    assert body["items"] == []


def test_list_returns_saved_clips(client: TestClient) -> None:
    headers, user_id = _auth(client)
    video_id = _upload_video(client, headers)
    _save_clip(video_id, user_id)

    body = client.get(f"/api/v1/videos/{video_id}/clips", headers=headers).json()
    assert body["count"] == 1
    clip = body["items"][0]
    assert clip["prompt"] == "a red car"
    assert clip["start"] == 0.0
    assert clip["end"] == 6.0
    assert clip["frame"] == 3.0
    assert clip["score"] == 0.81
    assert clip["created_at"]


def test_list_other_users_video_is_404(client: TestClient) -> None:
    mine, _ = _auth(client)
    video_id = _upload_video(client, mine)
    other, _ = _auth(client, email="other@example.com", name="Other Person")

    response = client.get(f"/api/v1/videos/{video_id}/clips", headers=other)
    assert response.status_code == 404


def test_list_never_leaks_other_users_clips(client: TestClient) -> None:
    mine, my_id = _auth(client)
    video_id = _upload_video(client, mine)
    _save_clip(video_id, my_id)

    # A second account can't reach the video, so their clips stay invisible.
    other, _ = _auth(client, email="other@example.com", name="Other Person")
    assert client.get(f"/api/v1/videos/{video_id}/clips", headers=other).status_code == 404


# ── Delete ─────────────────────────────────────────────────────


def test_delete_removes_one_clip(client: TestClient) -> None:
    headers, user_id = _auth(client)
    video_id = _upload_video(client, headers)
    clip_id = _save_clip(video_id, user_id)

    response = client.delete(f"/api/v1/videos/{video_id}/clips/{clip_id}", headers=headers)
    assert response.status_code == 200

    body = client.get(f"/api/v1/videos/{video_id}/clips", headers=headers).json()
    assert body["count"] == 0


def test_delete_someone_elses_clip_is_404(client: TestClient) -> None:
    mine, my_id = _auth(client)
    video_id = _upload_video(client, mine)
    clip_id = _save_clip(video_id, my_id)
    other, _ = _auth(client, email="other@example.com", name="Other Person")

    response = client.delete(
        f"/api/v1/videos/{video_id}/clips/{clip_id}",
        headers=other,
    )
    assert response.status_code == 404
    # The original owner still has it.
    body = client.get(f"/api/v1/videos/{video_id}/clips", headers=mine).json()
    assert body["count"] == 1


def test_clips_cascade_when_video_deleted(client: TestClient) -> None:
    headers, user_id = _auth(client)
    video_id = _upload_video(client, headers)
    _save_clip(video_id, user_id)

    response = client.delete(f"/api/v1/videos/{video_id}", headers=headers)
    assert response.status_code == 200

    # The video is gone, so the list is a 404 — and a direct row check shows
    # the clip was cascaded away, not orphaned.
    assert client.get(f"/api/v1/videos/{video_id}/clips", headers=headers).status_code == 404

    async def count() -> int:
        from sqlalchemy import func, select

        from app.videos.models import SavedClip

        async with SessionFactory() as db:
            return await db.scalar(select(func.count()).select_from(SavedClip))

    assert _run(count()) == 0
