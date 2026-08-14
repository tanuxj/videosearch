"""End-to-end tests for the search-history routes.

Skipped unless TEST_DATABASE_URL points at a reachable Postgres — see
tests/conftest.py. Mirrors the video tests' helpers so history rows can be
created against a real owned video.
"""

import io

import pytest
from fastapi.testclient import TestClient

from tests.conftest import needs_db

pytestmark = needs_db

SIGNUP = {"name": "Alex Rivera", "email": "alex@example.com", "password": "correct-horse-8"}

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64

CLIPS = [
    {"id": "frame-1", "start": 0.0, "end": 6.0, "frame": 3.0, "score": 0.81},
    {"id": "frame-2", "start": 10.0, "end": 16.0, "frame": 13.0, "score": 0.64},
]


def _auth_headers(client: TestClient, **signup_overrides: object) -> dict[str, str]:
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, **signup_overrides})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload_video(client: TestClient, headers: dict[str, str]) -> str:
    files = {"file": ("clip.mp4", io.BytesIO(FAKE_MP4), "video/mp4")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _record_search(
    client: TestClient,
    headers: dict[str, str],
    video_id: str,
    *,
    prompt: str = "a red car",
) -> dict:
    response = client.post(
        "/api/v1/history",
        headers=headers,
        json={
            "video_id": video_id,
            "prompt": prompt,
            "clips": CLIPS,
            "expanded": True,
            "min_score": 0.24,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── Auth ───────────────────────────────────────────────────────


def test_list_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/history").status_code == 401


def test_create_requires_auth(client: TestClient) -> None:
    response = client.post("/api/v1/history", json={"video_id": "0" * 36, "prompt": "x"})
    assert response.status_code == 401


# ── Create ─────────────────────────────────────────────────────


def test_create_records_the_search(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload_video(client, headers)

    body = _record_search(client, headers, video_id)

    assert body["video_id"] == video_id
    assert body["prompt"] == "a red car"
    assert body["expanded"] is True
    assert body["min_score"] == 0.24
    assert body["clips"] == CLIPS
    assert body["created_at"]


def test_create_rejects_unknown_video(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/api/v1/history",
        headers=headers,
        json={"video_id": "00000000-0000-0000-0000-000000000000", "prompt": "x", "clips": []},
    )
    assert response.status_code == 404


def test_create_rejects_someone_elses_video(client: TestClient) -> None:
    mine = _auth_headers(client)
    video_id = _upload_video(client, mine)
    _auth_headers(client, email="other@example.com", name="Other Person")

    response = client.post(
        "/api/v1/history",
        headers={"Authorization": f"Bearer {_signin_other(client)}"},
        json={"video_id": video_id, "prompt": "x", "clips": []},
    )
    assert response.status_code == 404


def _signin_other(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": SIGNUP["password"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": ""},
        {"prompt": "x" * 301},
        {"clips": [{"start": -1, "end": 2, "frame": 0, "score": 0.5}]},
        {"clips": [{"start": 0, "end": 2, "frame": 0, "score": 1.5}]},
    ],
)
def test_create_validates_shape(client: TestClient, payload: dict) -> None:
    headers = _auth_headers(client)
    video_id = _upload_video(client, headers)

    body = {"video_id": video_id, "clips": [], **payload}
    response = client.post("/api/v1/history", headers=headers, json=body)
    assert response.status_code == 422


# ── List ───────────────────────────────────────────────────────


def test_list_returns_only_my_searches(client: TestClient) -> None:
    mine = _auth_headers(client)
    video_id = _upload_video(client, mine)
    _record_search(client, mine, video_id, prompt="mine")

    # A second account must not see the first one's history.
    other = _auth_headers(client, email="other@example.com", name="Other Person")
    other_video = _upload_video(client, other)
    _record_search(client, other, other_video, prompt="theirs")

    body = client.get("/api/v1/history", headers=mine).json()
    assert body["count"] == 1
    assert [item["prompt"] for item in body["items"]] == ["mine"]

    body = client.get("/api/v1/history", headers=other).json()
    assert [item["prompt"] for item in body["items"]] == ["theirs"]


def test_list_is_newest_first(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload_video(client, headers)
    _record_search(client, headers, video_id, prompt="first")
    _record_search(client, headers, video_id, prompt="second")

    body = client.get("/api/v1/history", headers=headers).json()
    assert [item["prompt"] for item in body["items"]] == ["second", "first"]


# ── Delete ─────────────────────────────────────────────────────


def test_delete_removes_one_search(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload_video(client, headers)
    first = _record_search(client, headers, video_id, prompt="first")
    _record_search(client, headers, video_id, prompt="second")

    response = client.delete(f"/api/v1/history/{first['id']}", headers=headers)
    assert response.status_code == 200

    body = client.get("/api/v1/history", headers=headers).json()
    assert body["count"] == 1
    assert body["items"][0]["prompt"] == "second"


def test_delete_someone_elses_search_is_404(client: TestClient) -> None:
    mine = _auth_headers(client)
    video_id = _upload_video(client, mine)
    record = _record_search(client, mine, video_id)
    _auth_headers(client, email="other@example.com", name="Other Person")

    response = client.delete(
        f"/api/v1/history/{record['id']}",
        headers={"Authorization": f"Bearer {_signin_other(client)}"},
    )
    assert response.status_code == 404
    # The original owner still has it.
    assert client.get("/api/v1/history", headers=mine).json()["count"] == 1


def test_clear_removes_all_searches(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload_video(client, headers)
    _record_search(client, headers, video_id)
    _record_search(client, headers, video_id, prompt="another")

    response = client.delete("/api/v1/history", headers=headers)
    assert response.status_code == 200
    assert "2" in response.json()["detail"]

    assert client.get("/api/v1/history", headers=headers).json()["count"] == 0


def test_history_cascades_when_video_deleted(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload_video(client, headers)
    _record_search(client, headers, video_id)

    response = client.delete(f"/api/v1/videos/{video_id}", headers=headers)
    assert response.status_code == 200

    assert client.get("/api/v1/history", headers=headers).json()["count"] == 0
