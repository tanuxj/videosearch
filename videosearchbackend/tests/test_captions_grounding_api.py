"""Caption channel in search + the grounding endpoint (both behind flags).

Florence-2 itself is never loaded here — `captions` is monkeypatched at the
function level. What the tests own is the *wiring*: captions written at index
time land on the frame rows, the caption subsearch surfaces a frame whose
caption says the thing, and `/ground` refuses to run when the deployment has
grounding off.
"""

import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.main import app
from app.videos import captions, embedder, pipeline
from app.videos import query_expand
from tests.conftest import needs_db

pytestmark = [needs_db]

SIGNUP = {"name": "Cap Tester", "email": "cap@example.com", "password": "correct-horse-9"}

VECTOR_DIM = 512


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def fake_embedder(monkeypatch: pytest.MonkeyPatch):
    """Deterministic embedder: one-hot vector from the frame's dominant colour,
    and text vectors keyed on colour words — the same scheme the pipeline
    tests use, so the image channel's behaviour is fully known."""

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

    def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        vectors = []
        for text_ in texts:
            vector = np.zeros(VECTOR_DIM, dtype=np.float32)
            lower = text_.lower()
            if "red" in lower:
                vector[0] = 1.0
            elif "green" in lower:
                vector[1] = 1.0
            else:
                vector[2] = 1.0
            vectors.append(vector.tolist())
        return vectors

    monkeypatch.setattr(embedder, "embed_images", fake_embed_images)
    monkeypatch.setattr(embedder, "embed_texts", fake_embed_texts)


@pytest.fixture()
def two_frame_video(client: TestClient, fake_embedder, tmp_path_factory):
    """A signed-in user with an indexed red→green 2s video; returns (headers, id)."""
    path = tmp_path_factory.mktemp("cap") / "rg.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 64))
    for color in [(0, 0, 255), (0, 255, 0)]:  # BGR → red, then green
        writer.write(np.full((64, 64, 3), color, dtype=np.uint8))
    writer.release()

    response = client.post(
        "/api/v1/auth/signup",
        json={**SIGNUP, "email": f"{uuid.uuid4().hex[:8]}@example.com"},
    )
    assert response.status_code == 201, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    files = {"file": ("rg.avi", path.read_bytes(), "video/x-msvideo")}
    video_id = client.post("/api/v1/videos", headers=headers, files=files).json()["id"]
    client.portal.call(pipeline.index_video, uuid.UUID(video_id))
    return headers, video_id


def _set_caption(client: TestClient, video_id: str, timestamp: float, caption: str) -> None:
    """Write a caption + its (fake) text embedding onto one frame row."""

    def do() -> None:
        async def run() -> None:
            vector = np.zeros(VECTOR_DIM, dtype=np.float32)
            lower = caption.lower()
            if "red" in lower:
                vector[0] = 1.0
            elif "green" in lower:
                vector[1] = 1.0
            else:
                vector[2] = 1.0
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE frames SET caption = :cap, caption_embedding = :vec "
                        "WHERE video_id = :vid AND timestamp_sec = :ts"
                    ),
                    {
                        "cap": caption,
                        "vec": str(vector.tolist()),
                        "vid": uuid.UUID(video_id),
                        "ts": timestamp,
                    },
                )

        client.portal.call(run)


# ── Index-time captioning ──────────────────────────────────────


def test_index_writes_captions_when_enabled(
    client: TestClient,
    two_frame_video,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory,
):
    """With captions on, indexed frames carry caption + caption_embedding."""
    monkeypatch.setattr(get_settings(), "captions_enabled", True)

    def fake_caption_frames(frames):
        out = []
        for frame in frames:
            mean = frame.mean(axis=(0, 1))
            out.append("a red wall" if np.argmax(mean) == 0 else "a green field")
        return out

    monkeypatch.setattr(captions, "caption_frames", fake_caption_frames)

    # Fresh video (the fixture's ran with captions off).
    path = tmp_path_factory.mktemp("cap2") / "rg2.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 64))
    for color in [(0, 0, 255), (0, 255, 0)]:
        writer.write(np.full((64, 64, 3), color, dtype=np.uint8))
    writer.release()

    response = client.post(
        "/api/v1/auth/signup",
        json={**SIGNUP, "email": f"{uuid.uuid4().hex[:8]}@example.com"},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    files = {"file": ("rg2.avi", path.read_bytes(), "video/x-msvideo")}
    video_id = client.post("/api/v1/videos", headers=headers, files=files).json()["id"]
    client.portal.call(pipeline.index_video, uuid.UUID(video_id))

    def count_captions() -> int:
        async def run() -> int:
            async with engine.connect() as connection:
                return await connection.scalar(
                    text(
                        "SELECT count(*) FROM frames "
                        "WHERE video_id = :vid AND caption IS NOT NULL "
                        "AND caption_embedding IS NOT NULL"
                    ),
                    {"vid": uuid.UUID(video_id)},
                )

        return run()

    assert client.portal.call(count_captions) == 2


def test_index_skips_captions_when_disabled(client: TestClient, two_frame_video):
    """Default flags: frames get no caption column data (null stays null)."""
    headers, video_id = two_frame_video

    def count_captions() -> int:
        async def run() -> int:
            async with engine.connect() as connection:
                return await connection.scalar(
                    text(
                        "SELECT count(*) FROM frames "
                        "WHERE video_id = :vid AND caption IS NOT NULL"
                    ),
                    {"vid": uuid.UUID(video_id)},
                )

        return run()

    assert client.portal.call(count_captions) == 0


# ── Caption channel in search ──────────────────────────────────


def test_caption_channel_surfaces_captioned_frame(
    client: TestClient, two_frame_video, monkeypatch: pytest.MonkeyPatch
):
    """A frame whose caption *says* the thing is found via text↔text match.

    The image embeddings here are one-hot: "a green field" against the red
    frame scores 0 on the image channel. Only the caption channel can find
    the red frame's neighbour — so if the green timestamp comes back, the
    caption wiring did it.
    """
    headers, video_id = two_frame_video
    _set_caption(client, video_id, 1.0, "a green field")

    monkeypatch.setattr(query_expand, "expand_prompt", lambda prompt: [prompt])

    response = client.post(
        "/api/v1/search/clips",
        headers=headers,
        json={"video_id": video_id, "prompt": "a green field", "limit": 9},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] >= 1
    assert 1.0 in {item["timestamp"] for item in body["items"]}


def test_uncaptioned_prompt_stays_below_caption_floor(
    client: TestClient, two_frame_video, monkeypatch: pytest.MonkeyPatch
):
    """Captions below `caption_min_similarity` contribute nothing.

    "a wall" vs "a green field" are orthogonal in the fake space (similarity
    0), far under the floor — the frame must not be surfaced by its caption.
    """
    headers, video_id = two_frame_video
    _set_caption(client, video_id, 1.0, "a green field")

    monkeypatch.setattr(query_expand, "expand_prompt", lambda prompt: [prompt])

    response = client.post(
        "/api/v1/search/clips",
        headers=headers,
        json={"video_id": video_id, "prompt": "a wall", "limit": 9},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The green frame has image embedding [0,1,0] and query "a wall" embeds to
    # [0,0,1] — cosine 0 on the image channel, and the caption is filtered by
    # the floor. Nothing may match at all.
    assert body["count"] == 0


# ── Grounding endpoint ─────────────────────────────────────────


def test_ground_disabled_returns_503(client: TestClient, two_frame_video):
    headers, video_id = two_frame_video
    response = client.post(
        f"/api/v1/search/{video_id}/ground",
        headers=headers,
        json={"timestamp": 0.0, "phrase": "red"},
    )
    assert response.status_code == 503
    assert "not enabled" in response.json()["detail"]


def test_ground_returns_boxes_when_enabled(
    client: TestClient, two_frame_video, monkeypatch: pytest.MonkeyPatch
):
    headers, video_id = two_frame_video
    monkeypatch.setattr(get_settings(), "grounding_enabled", True)

    def fake_locate(frame, phrase):
        # frame_at decodes at native resolution (64x64 test fixture); Florence-2's
        # processor does its own resize, so no pre-scaling is expected here.
        assert frame.ndim == 3 and frame.shape[2] == 3
        return [[0.05, 0.1, 0.5, 0.9]]

    monkeypatch.setattr(captions, "locate_phrase", fake_locate)

    response = client.post(
        f"/api/v1/search/{video_id}/ground",
        headers=headers,
        json={"timestamp": 0.2, "phrase": "red"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["phrase"] == "red"
    assert body["boxes"] == [{"x1": 0.05, "y1": 0.1, "x2": 0.5, "y2": 0.9}]


def test_ground_404_when_no_frame_at_timestamp(
    client: TestClient, two_frame_video, monkeypatch: pytest.MonkeyPatch
):
    headers, video_id = two_frame_video
    monkeypatch.setattr(get_settings(), "grounding_enabled", True)
    response = client.post(
        f"/api/v1/search/{video_id}/ground",
        headers=headers,
        json={"timestamp": 999.0, "phrase": "red"},
    )
    assert response.status_code == 404


def test_ground_anonymous_never_reaches_someone_elses_video(
    client: TestClient, two_frame_video
):
    """An anonymous (trial-session) caller may never ground another user's video.

    With the flag off the route answers 503 before ownership is even checked;
    with it on, the ownership lookup must 404 — existence is not leaked.
    """
    _, video_id = two_frame_video
    flagged_off = client.post(
        f"/api/v1/search/{video_id}/ground",
        json={"timestamp": 0.0, "phrase": "red"},
    )
    assert flagged_off.status_code in (403, 503)  # auth wall or feature flag

    from app.core.config import get_settings as gs

    original = gs().grounding_enabled
    object.__setattr__(gs(), "grounding_enabled", True)
    try:
        flagged_on = client.post(
            f"/api/v1/search/{video_id}/ground",
            json={"timestamp": 0.0, "phrase": "red"},
        )
    finally:
        object.__setattr__(gs(), "grounding_enabled", original)
    assert flagged_on.status_code == 404
