"""End-to-end tests for the indexing pipeline and semantic search.

These exercise the real pipeline (OpenCV frame extraction, pgvector inserts,
the search query) with only the CLIP embedder mocked — a real model download
has no place in the test suite.

A tiny 3-second video is generated with OpenCV: one solid colour per second
(red, green, blue). The mocked embedder turns each frame into a one-hot
vector keyed on its dominant colour, so search results are fully predictable.
"""

import io
import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import engine
from app.videos import embedder, pipeline
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


def test_search_returns_best_matching_frame_first(
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
    assert body["count"] == 3
    # Red is frame 0 → timestamp 0.0, score 1.0.
    assert body["items"][0]["timestamp"] == 0.0
    assert body["items"][0]["score"] == 1.0
    assert body["items"][0]["start"] == 0.0
    assert body["items"][0]["end"] > 0.0


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
    # Green is frame 1 → timestamp 1.0 ranks first.
    assert items[0]["timestamp"] == 1.0
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
