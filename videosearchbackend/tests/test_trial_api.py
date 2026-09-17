"""Homepage-trial flow: anonymous upload/search works, product features 401.

The trial is the boundary between the public homepage demo and the product:
a cookie-session visitor may upload, index and search, while every
persistent/monetised route (clip download, share links, deletion, transcript
generation) answers 401 until they sign up. These tests exercise that
boundary through the HTTP surface — no trial-specific test double — because
the guarantee users care about is exactly "these endpoints behave this way
with no Authorization header".

Storage is a throwaway dir and indexing is stubbed, so uploads resolve to
`ready` without the CLIP model; `purge_expired_trials` is called directly to
verify the deletion promise (row + file) without waiting out the clock.
"""

import os
import uuid as uuid_module

os.environ.setdefault("AUTH_ENABLED", "true")
os.environ.setdefault("TRIAL_ENABLED", "true")

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.videos.trial import purge_expired_trials

from tests.conftest import needs_db

pytestmark = [needs_db]

PNG_1PX = b"\x89PNG\r\n\x1a\n" + b"0" * 32  # contents don't matter; ext does


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _signup(client: TestClient, email: str) -> dict:
    """Create an account and replay its access token, like the real client.

    The frontend holds the token in memory and sends it on every request;
    TestClient must do the same or the next call looks anonymous (a trial)
    again.
    """
    response = client.post(
        "/api/v1/auth/signup",
        json={"name": "Tester", "email": email, "password": "password123"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    client.headers.update(
        {"Authorization": f"Bearer {payload['access_token']}"}
    )
    return payload


def _upload_as_trial(client: TestClient) -> dict:
    """Upload through the trial path: no Authorization header at all."""
    response = client.post(
        "/api/v1/videos",
        files={"file": ("trial-clip.mp4", PNG_1PX, "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_trial_upload_stamps_expiry(client: TestClient):
    video = _upload_as_trial(client)
    assert video["expires_at"] is not None
    deadline = datetime.fromisoformat(video["expires_at"].replace("Z", "+00:00"))
    remaining = deadline - datetime.now(UTC)
    assert timedelta(minutes=29) < remaining <= timedelta(minutes=30)


def test_trial_list_and_get_work(client: TestClient):
    video = _upload_as_trial(client)
    listed = client.get("/api/v1/videos")
    assert listed.status_code == 200
    assert any(item["id"] == video["id"] for item in listed.json()["items"])
    got = client.get(f"/api/v1/videos/{video['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == video["id"]


def test_registered_upload_has_no_expiry(client: TestClient):
    _signup(client, "owner@example.com")
    response = client.post(
        "/api/v1/videos",
        files={"file": ("kept.mp4", PNG_1PX, "video/mp4")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["expires_at"] is None


def test_registered_user_sees_their_videos_after_trial_uploads(client: TestClient):
    """Trial uploads belong to the guest session; signup starts a clean lib."""
    _upload_as_trial(client)
    _signup(client, "fresh@example.com")
    listed = client.get("/api/v1/videos").json()
    assert listed["items"] == []


def test_trial_search_route_404s_on_unknown_video(client: TestClient):
    """The search route is trial-accessible; ownership is still enforced."""
    response = client.post(
        "/api/v1/search/clips",
        json={"video_id": "00000000-0000-0000-0000-0000000000aa", "prompt": "a car"},
    )
    assert response.status_code == 404


def test_trial_cannot_download_clip(client: TestClient):
    video = _upload_as_trial(client)
    response = client.get(f"/api/v1/videos/{video['id']}/clip?start=0&end=1")
    assert response.status_code == 401
    assert "account" in response.json()["detail"].lower()


def test_trial_cannot_share(client: TestClient):
    video = _upload_as_trial(client)
    response = client.get(f"/api/v1/videos/{video['id']}/share")
    assert response.status_code == 401


def test_trial_cannot_delete_or_move(client: TestClient):
    video = _upload_as_trial(client)
    response = client.delete(f"/api/v1/videos/{video['id']}")
    assert response.status_code == 401
    moved = client.patch(
        f"/api/v1/videos/{video['id']}", json={"workspace_id": None}
    )
    assert moved.status_code == 401


def test_trial_cannot_start_transcription(client: TestClient):
    video = _upload_as_trial(client)
    response = client.post(f"/api/v1/videos/{video['id']}/transcribe")
    assert response.status_code == 401


def test_trial_can_still_read_transcript_and_captions(client: TestClient):
    video = _upload_as_trial(client)
    transcript = client.get(f"/api/v1/videos/{video['id']}/transcript")
    assert transcript.status_code == 200
    captions = client.get(f"/api/v1/videos/{video['id']}/captions.vtt")
    assert captions.status_code == 200


def test_registered_user_passes_the_gates(client: TestClient):
    _signup(client, "paid@example.com")
    response = client.post(
        "/api/v1/videos",
        files={"file": ("mine.mp4", PNG_1PX, "video/mp4")},
    )
    assert response.status_code == 201
    video = response.json()
    # Any gated route must accept the same session the trial was refused on.
    assert client.get(f"/api/v1/videos/{video['id']}/clip?start=0&end=1").status_code in (
        200,
        503,  # ffmpeg unavailable in CI — the gate passed either way
    )
    assert client.get(f"/api/v1/videos/{video['id']}/share").status_code == 200


def test_signup_clears_this_browser_trial_videos(client: TestClient):
    """Signing up from the trial browser must not adopt the trial's videos."""
    video = _upload_as_trial(client)
    _signup(client, "converted@example.com")
    listed = client.get("/api/v1/videos").json()
    assert all(item["id"] != video["id"] for item in listed["items"])


def test_expired_trial_video_is_purged(client: TestClient):
    video = _upload_as_trial(client)
    # Age the row past its deadline the honest way — the column is the
    # contract, and the sweep only deletes what the column says. Both DB
    # hops run on the TestClient's own loop via `portal.call`, like
    # test_pipeline_api — a second asyncio.run would fight the loop the
    # app's pooled connections are bound to.
    from app.db.session import SessionFactory
    from app.videos.models import Video

    async def age_row():
        async with SessionFactory() as db:
            row = await db.get(Video, uuid_module.UUID(video["id"]))
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()

    client.portal.call(age_row)
    purged = client.portal.call(purge_expired_trials)
    assert purged >= 1
    assert client.get(f"/api/v1/videos/{video['id']}").status_code == 404


def test_health_reports_flags(client: TestClient):
    body = client.get("/api/v1/health").json()
    assert body["auth_enabled"] is True
