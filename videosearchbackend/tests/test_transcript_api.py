"""End-to-end tests for the transcript and captions routes.

Skipped unless TEST_DATABASE_URL points at a reachable Postgres — see
tests/conftest.py. Segments are inserted directly rather than transcribed:
the ASR call itself is covered by tests/test_transcribe.py, and these are
about what the API hands the player.
"""

import asyncio
import io
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.videos.models import TranscriptSegment, Video
from tests.conftest import needs_db

pytestmark = needs_db

SIGNUP = {"name": "Rae Okafor", "email": "rae@example.com", "password": "correct-horse-8"}

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


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


def _auth_headers(client: TestClient, **overrides: object) -> dict[str, str]:
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, **overrides})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(client: TestClient, headers: dict[str, str]) -> dict:
    files = {"file": ("talk.mp4", io.BytesIO(FAKE_MP4), "video/mp4")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 201, response.text
    return response.json()


def _write_transcript(video_id: str, language: str, lines: list[tuple[float, float, str]]):
    """Put a finished transcript on a video, as the pipeline would."""

    async def work(session_factory):
        async with session_factory() as db:
            video = await db.get(Video, uuid.UUID(video_id))
            video.transcript_status = "ready"
            video.language = language
            for index, (start, end, text) in enumerate(lines):
                db.add(
                    TranscriptSegment(
                        video_id=uuid.UUID(video_id),
                        idx=index,
                        start_sec=start,
                        end_sec=end,
                        text=text,
                    )
                )
            await db.commit()

    return work


LINES = [(0.0, 2.5, "Welcome to the demo."), (2.5, 6.0, "Let's look at the results.")]


# ── Auth and ownership ─────────────────────────────────────────


def test_transcript_requires_auth(client: TestClient) -> None:
    assert client.get(f"/api/v1/videos/{uuid.uuid4()}/transcript").status_code == 401


def test_captions_require_auth(client: TestClient) -> None:
    assert client.get(f"/api/v1/videos/{uuid.uuid4()}/captions.vtt").status_code == 401


def test_transcript_of_another_users_video_is_404(client: TestClient) -> None:
    owner = _auth_headers(client)
    video = _upload(client, owner)
    intruder = _auth_headers(client, email="mallory@example.com")

    assert (
        client.get(f"/api/v1/videos/{video['id']}/transcript", headers=intruder).status_code == 404
    )
    assert (
        client.get(f"/api/v1/videos/{video['id']}/captions.vtt", headers=intruder).status_code
        == 404
    )


# ── Before transcription finishes ──────────────────────────────


def test_fresh_upload_reports_a_pending_transcript(client: TestClient) -> None:
    headers = _auth_headers(client)
    video = _upload(client, headers)

    # The video row itself carries the status, so the library list is enough
    # to know whether to keep polling.
    assert video["transcript_status"] == "pending"
    assert video["language"] is None

    body = client.get(f"/api/v1/videos/{video['id']}/transcript", headers=headers).json()
    assert body["status"] == "pending"
    assert body["segments"] == []
    assert body["count"] == 0


def test_captions_are_valid_vtt_even_with_no_transcript(client: TestClient) -> None:
    """The player attaches the track unconditionally, so this must not 404."""
    headers = _auth_headers(client)
    video = _upload(client, headers)

    response = client.get(f"/api/v1/videos/{video['id']}/captions.vtt", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/vtt")
    assert response.text.strip() == "WEBVTT"


# ── After transcription finishes ───────────────────────────────


def test_transcript_returns_segments_and_language(client: TestClient) -> None:
    headers = _auth_headers(client)
    video = _upload(client, headers)
    _run(_write_transcript(video["id"], "en", LINES))

    body = client.get(f"/api/v1/videos/{video['id']}/transcript", headers=headers).json()
    assert body["status"] == "ready"
    assert body["language"] == "en"
    assert body["count"] == 2
    assert [item["text"] for item in body["segments"]] == [line[2] for line in LINES]
    assert body["segments"][0]["start"] == 0.0
    assert body["segments"][1]["end"] == 6.0


def test_transcript_is_visible_while_frames_still_index(client: TestClient) -> None:
    """The whole point of the split status: text lands before the video is ready."""
    headers = _auth_headers(client)
    video = _upload(client, headers)
    _run(_write_transcript(video["id"], "en", LINES))

    listed = client.get("/api/v1/videos", headers=headers).json()["items"][0]
    assert listed["status"] == "processing"
    assert listed["transcript_status"] == "ready"


def test_captions_render_the_transcript_as_vtt(client: TestClient) -> None:
    headers = _auth_headers(client)
    video = _upload(client, headers)
    _run(_write_transcript(video["id"], "en", LINES))

    response = client.get(f"/api/v1/videos/{video['id']}/captions.vtt", headers=headers)
    assert response.status_code == 200
    assert response.text.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.500" in response.text
    assert "Welcome to the demo." in response.text
    assert "00:00:02.500 --> 00:00:06.000" in response.text


def test_deleting_a_video_removes_its_transcript(client: TestClient) -> None:
    headers = _auth_headers(client)
    video = _upload(client, headers)
    _run(_write_transcript(video["id"], "en", LINES))

    assert client.delete(f"/api/v1/videos/{video['id']}", headers=headers).status_code == 200
    # The cascade is the DB's job; assert the rows are actually gone.
    assert _run(_count_segments(video["id"])) == 0


def _count_segments(video_id: str):
    async def work(session_factory) -> int:
        async with session_factory() as db:
            return await db.scalar(
                select(func.count())
                .select_from(TranscriptSegment)
                .where(TranscriptSegment.video_id == uuid.UUID(video_id))
            )

    return work
