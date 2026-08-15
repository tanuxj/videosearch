"""End-to-end tests for the indexing pipeline and semantic search.

These exercise the real pipeline (OpenCV frame extraction, pgvector inserts,
the search query) with only the CLIP embedder mocked — a real model download
has no place in the test suite.

A tiny 3-second video is generated with OpenCV: one solid colour per second
(red, green, blue). The mocked embedder turns each frame into a one-hot
vector keyed on its dominant colour, so search results are fully predictable.
"""

import io
import subprocess
import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.videos import embedder, pipeline, query_expand
from app.videos.clips import ffmpeg_binary
from tests.conftest import needs_db

pytestmark = needs_db

SIGNUP = {"name": "Alex Rivera", "email": "alex@example.com", "password": "correct-horse-8"}

VECTOR_DIM = 512


@pytest.fixture(scope="module")
def clip_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """A 3-second 64x64 AVI: red, green, blue — one solid second each."""
    path = tmp_path_factory.mktemp("clips") / "scenes.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 64))
    # BGR values whose BGR→RGB conversion yields red, green, blue.
    colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0)]
    for color in colors:
        frame = np.full((64, 64, 3), color, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path.read_bytes()


@pytest.fixture(scope="module")
def audio_only_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """A 3-second audio-only webm — a mic-only recording, no video track."""
    path = tmp_path_factory.mktemp("audio") / "voice.webm"
    subprocess.run(
        [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


@pytest.fixture()
def fake_embedder(monkeypatch: pytest.MonkeyPatch):
    """Deterministic embedder: one-hot vector from the frame's dominant colour."""

    def dominant_index(image: np.ndarray) -> int:
        mean = image.mean(axis=(0, 1))  # RGB means
        return int(np.argmax(mean))

    def fake_embed_images(images) -> list[list[float]]:
        vectors = []
        for image in images:
            vector = np.zeros(VECTOR_DIM, dtype=np.float32)
            vector[dominant_index(image)] = 1.0
            vectors.append(vector.tolist())
        return vectors

    def fake_embed_text(prompt: str) -> list[float]:
        vector = np.zeros(VECTOR_DIM, dtype=np.float32)
        lower = prompt.lower()
        if "red" in lower:
            vector[0] = 1.0
        elif "green" in lower:
            vector[1] = 1.0
        else:
            vector[2] = 1.0
        return vector.tolist()

    monkeypatch.setattr(embedder, "embed_images", fake_embed_images)
    monkeypatch.setattr(embedder, "embed_text", fake_embed_text)


def _signup(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/signup", json=SIGNUP)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(client: TestClient, headers: dict[str, str], clip: bytes) -> str:
    files = {"file": ("scenes.avi", io.BytesIO(clip), "video/x-msvideo")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _index(client: TestClient, video_id: str) -> None:
    """Run the pipeline on the app's own event loop."""
    client.portal.call(pipeline.index_video, uuid.UUID(video_id))


# ── Indexing ───────────────────────────────────────────────────


def test_upload_then_index_marks_video_ready(
    client: TestClient, fake_embedder: None, clip_bytes: bytes
) -> None:
    headers = _signup(client)
    video_id = _upload(client, headers, clip_bytes)

    # Still processing until the pipeline runs.
    status = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()["status"]
    assert status == "processing"

    _index(client, video_id)

    body = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
    assert body["status"] == "ready"
    assert body["frames_total"] == 3
    assert body["frames_indexed"] == 3
    assert body["duration_seconds"] == pytest.approx(3.0, abs=0.5)


def test_indexed_frames_are_in_pgvector(
    client: TestClient, fake_embedder: None, clip_bytes: bytes
) -> None:
    headers = _signup(client)
    video_id = _upload(client, headers, clip_bytes)
    _index(client, video_id)

    async def count_frames() -> int:
        async with engine.connect() as connection:
            return await connection.scalar(
                text("SELECT count(*) FROM frames WHERE video_id = :vid"),
                {"vid": uuid.UUID(video_id)},
            )

    assert client.portal.call(count_frames) == 3


def test_index_is_idempotent(client: TestClient, fake_embedder: None, clip_bytes: bytes) -> None:
    headers = _signup(client)
    video_id = _upload(client, headers, clip_bytes)
    _index(client, video_id)
    _index(client, video_id)  # second run must be a no-op

    body = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
    assert body["status"] == "ready"
    assert body["frames_indexed"] == 3


def test_audio_only_upload_is_ready_without_frames(
    client: TestClient, audio_only_bytes: bytes
) -> None:
    """An audio-only recording has nothing to frame-index: it lands ready, not failed.

    This is the path a mic-only recording from the Record tab takes: OpenCV
    can't open the file, and the pipeline must recognise that as "nothing to
    index" instead of a failure — the video is ready with zero frames (its
    transcript still comes from the audio).
    """
    headers = _signup(client)
    files = {"file": ("voice.webm", io.BytesIO(audio_only_bytes), "audio/webm")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 201
    video_id = response.json()["id"]

    _index(client, video_id)

    body = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
    assert body["status"] == "ready"
    assert body["frames_total"] == 0
    assert body["frames_indexed"] == 0
    assert body["duration_seconds"] == pytest.approx(3.0, abs=0.5)

    async def count_frames() -> int:
        async with engine.connect() as connection:
            return await connection.scalar(
                text("SELECT count(*) FROM frames WHERE video_id = :vid"),
                {"vid": uuid.UUID(video_id)},
            )

    assert client.portal.call(count_frames) == 0


def test_probe_file_flags_audio_only_recordings(
    audio_only_bytes: bytes, clip_bytes: bytes, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """cv2 can't open audio-only files; the ffmpeg fallback tells them apart.

    A mic-only recording raises AudioOnlyFile with its real duration, while a
    file with a video track (or a non-media blob) stays a genuine failure.
    """
    workdir = tmp_path_factory.mktemp("probe")
    audio = workdir / "voice.webm"
    audio.write_bytes(audio_only_bytes)

    with pytest.raises(pipeline.AudioOnlyFile) as exc_info:
        pipeline.probe_file(audio)
    assert exc_info.value.duration == pytest.approx(3.0, abs=0.5)

    # The fallback distinguishes the three cases by what ffmpeg sees.
    assert pipeline._probe_audio_only_duration(audio) == pytest.approx(3.0, abs=0.5)
    video = workdir / "scenes.avi"
    video.write_bytes(clip_bytes)
    assert pipeline._probe_audio_only_duration(video) is None  # has a video track
    junk = workdir / "junk.mp4"
    junk.write_bytes(b"this is not a video at all")
    assert pipeline._probe_audio_only_duration(junk) is None  # unreadable, not audio-only


def test_failed_index_marks_video_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _signup(client)
    files = {"file": ("broken.mp4", io.BytesIO(b"this is not a video at all"), "video/mp4")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 201
    video_id = response.json()["id"]

    _index(client, video_id)

    body = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
    assert body["status"] == "failed"
    assert body["error"]


def test_failed_index_cleans_up_partial_frames(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A failure after some chunks committed must not leak frame rows."""
    # 40 frames at 1fps → the first _EMBED_CHUNK (32) commits, the second fails.
    # Fixed-rate sampling (scene-aware off) so every frame is a candidate.
    monkeypatch.setattr(get_settings(), "scene_aware_sampling", False)
    path = tmp_path_factory.mktemp("clips") / "long.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 64))
    for _ in range(40):
        writer.write(np.full((64, 64, 3), (255, 0, 0), dtype=np.uint8))
    writer.release()

    calls = {"n": 0}

    def failing_embed(images):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom mid-pipeline")
        return [[1.0] + [0.0] * (VECTOR_DIM - 1) for _ in images]

    monkeypatch.setattr(embedder, "embed_images", failing_embed)

    headers = _signup(client)
    files = {"file": ("long.avi", io.BytesIO(path.read_bytes()), "video/x-msvideo")}
    video_id = client.post("/api/v1/videos", headers=headers, files=files).json()["id"]
    _index(client, video_id)

    body = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
    assert body["status"] == "failed"
    assert calls["n"] == 2  # first chunk embedded, second exploded

    async def count_frames() -> int:
        async with engine.connect() as connection:
            return await connection.scalar(
                text("SELECT count(*) FROM frames WHERE video_id = :vid"),
                {"vid": uuid.UUID(video_id)},
            )

    assert client.portal.call(count_frames) == 0


# ── Search ─────────────────────────────────────────────────────


def test_search_returns_best_matching_scene_first(
    client: TestClient, fake_embedder: None, clip_bytes: bytes
) -> None:
    headers = _signup(client)
    video_id = _upload(client, headers, clip_bytes)
    _index(client, video_id)

    response = client.post(
        "/api/v1/search/clips",
        headers=headers,
        json={"video_id": video_id, "prompt": "a red scene", "limit": 3},
    )
    assert response.status_code == 200

    body = response.json()
    # Red is frame 0 (score 1.0); green/blue score 0.0 and fall under the
    # minimum-similarity threshold, so they are not returned at all.
    assert body["count"] == 1
    assert body["items"][0]["timestamp"] == 0.0
    assert body["items"][0]["score"] == 1.0
    assert body["items"][0]["start"] == 0.0
    assert body["items"][0]["end"] > 0.0
    assert body["min_score"] > 0.0


def test_search_ranks_all_colours_correctly(
    client: TestClient, fake_embedder: None, clip_bytes: bytes
) -> None:
    headers = _signup(client)
    video_id = _upload(client, headers, clip_bytes)
    _index(client, video_id)

    response = client.post(
        "/api/v1/search/clips",
        headers=headers,
        json={"video_id": video_id, "prompt": "green grass", "limit": 3},
    )
    items = response.json()["items"]
    # Green is frame 1 → timestamp 1.0 ranks first; blue is filtered by the
    # threshold, so only the green scene survives.
    assert len(items) == 1
    assert items[0]["timestamp"] == 1.0
    assert items[0]["score"] == 1.0


def test_search_no_matching_scene_returns_empty(
    client: TestClient, fake_embedder: None, clip_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = _signup(client)
    video_id = _upload(client, headers, clip_bytes)
    _index(client, video_id)

    # An embedding orthogonal to every colour's one-hot → 0.0 similarity.
    vector = [0.0] * VECTOR_DIM
    vector[3] = 1.0
    monkeypatch.setattr(embedder, "embed_text", lambda prompt: vector)

    response = client.post(
        "/api/v1/search/clips",
        headers=headers,
        json={"video_id": video_id, "prompt": "a purple elephant", "limit": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["items"] == []


def test_search_uses_best_score_across_expanded_variants(
    client: TestClient,
    fake_embedder: None,
    clip_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expansion surfaces scenes the raw prompt alone would miss.

    The fake embedder maps "red" → one-hot[0], "green" → one-hot[1], so the
    raw prompt "green grass" matches only the green frame. Adding a red
    variant should surface the red frame too — each frame keeps its best score
    across variants.
    """
    headers = _signup(client)
    video_id = _upload(client, headers, clip_bytes)
    _index(client, video_id)

    # Narrow the merge window so the two colours read as separate scenes.
    monkeypatch.setattr(get_settings(), "search_merge_window_seconds", 0.5)
    monkeypatch.setattr(
        query_expand,
        "expand_prompt",
        lambda prompt: [prompt, "a red scene"],
    )

    response = client.post(
        "/api/v1/search/clips",
        headers=headers,
        json={"video_id": video_id, "prompt": "green grass", "limit": 9},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["expanded"] is True
    assert {item["timestamp"] for item in body["items"]} == {0.0, 1.0}


def test_search_merges_adjacent_matches_into_one_scene(
    client: TestClient,
    fake_embedder: None,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three consecutive red seconds are one scene spanning 0 → end, not three."""
    # Fixed-rate sampling so all three frames exist to merge.
    monkeypatch.setattr(get_settings(), "scene_aware_sampling", False)
    path = tmp_path_factory.mktemp("clips") / "all-red.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 64))
    for _ in range(3):
        writer.write(np.full((64, 64, 3), (0, 0, 255), dtype=np.uint8))
    writer.release()

    headers = _signup(client)
    files = {"file": ("all-red.avi", io.BytesIO(path.read_bytes()), "video/x-msvideo")}
    video_id = client.post("/api/v1/videos", headers=headers, files=files).json()["id"]
    _index(client, video_id)

    response = client.post(
        "/api/v1/search/clips",
        headers=headers,
        json={"video_id": video_id, "prompt": "a red scene", "limit": 9},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["start"] == 0.0
    # Frames at t=0, 1, 2 merge; the window is clamped to the 3s duration.
    assert items[0]["end"] == pytest.approx(3.0, abs=0.05)
    assert items[0]["score"] == 1.0


def test_search_before_indexing_is_409(client: TestClient, clip_bytes: bytes) -> None:
    headers = _signup(client)
    video_id = _upload(client, headers, clip_bytes)

    response = client.post(
        "/api/v1/search/clips",
        headers=headers,
        json={"video_id": video_id, "prompt": "anything", "limit": 3},
    )
    assert response.status_code == 409


def test_search_someone_elses_video_is_404(
    client: TestClient, fake_embedder: None, clip_bytes: bytes
) -> None:
    headers = _signup(client)
    video_id = _upload(client, headers, clip_bytes)
    _index(client, video_id)

    client.post(
        "/api/v1/auth/signup",
        json={"name": "Other", "email": "other@example.com", "password": SIGNUP["password"]},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": SIGNUP["password"]},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.post(
        "/api/v1/search/clips",
        headers=other_headers,
        json={"video_id": video_id, "prompt": "anything", "limit": 3},
    )
    assert response.status_code == 404


def test_search_requires_auth(client: TestClient, clip_bytes: bytes) -> None:
    response = client.post(
        "/api/v1/search/clips",
        json={"video_id": str(uuid.uuid4()), "prompt": "anything", "limit": 3},
    )
    assert response.status_code == 401


def test_scene_aware_sampling_skips_redundant_frames(
    client: TestClient, fake_embedder: None, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """40s video: 20s solid red then 20s solid blue.

    Scene-aware sampling (default on) keeps the first frame of each static run
    plus one frame every SCENE_MAX_GAP_SECONDS (6s) — 8 frames instead of 40,
    and both runs remain searchable.
    """
    path = tmp_path_factory.mktemp("clips") / "two-runs.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 64))
    for _ in range(20):
        writer.write(np.full((64, 64, 3), (0, 0, 255), dtype=np.uint8))
    for _ in range(20):
        writer.write(np.full((64, 64, 3), (255, 0, 0), dtype=np.uint8))
    writer.release()

    headers = _signup(client)
    files = {"file": ("two-runs.avi", io.BytesIO(path.read_bytes()), "video/x-msvideo")}
    video_id = client.post("/api/v1/videos", headers=headers, files=files).json()["id"]
    _index(client, video_id)

    body = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
    assert body["status"] == "ready"
    # Kept: red at 0,6,12,18 then blue at 20,26,32,38.
    assert body["frames_indexed"] == 8
    assert body["frames_total"] == 8

    async def timestamps() -> list[float]:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT timestamp_sec FROM frames WHERE video_id = :vid ORDER BY timestamp_sec"
                ),
                {"vid": uuid.UUID(video_id)},
            )
            return [row[0] for row in rows]

    assert client.portal.call(timestamps) == [0.0, 6.0, 12.0, 18.0, 20.0, 26.0, 32.0, 38.0]
