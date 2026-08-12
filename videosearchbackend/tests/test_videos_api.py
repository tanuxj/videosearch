"""End-to-end tests for the video routes.

Skipped unless TEST_DATABASE_URL points at a reachable Postgres — see
tests/conftest.py. Storage is forced to the local disk backend, so these
tests never touch a real R2 bucket.
"""

import io

import pytest
from fastapi.testclient import TestClient

from tests.conftest import needs_db

pytestmark = needs_db

SIGNUP = {"name": "Alex Rivera", "email": "alex@example.com", "password": "correct-horse-8"}

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def _auth_headers(client: TestClient, **signup_overrides: object) -> dict[str, str]:
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, **signup_overrides})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "clip.mp4",
    content: bytes = FAKE_MP4,
) -> dict:
    files = {"file": (name, io.BytesIO(content), "video/mp4")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 201, response.text
    return response.json()


# ── Auth ───────────────────────────────────────────────────────


def test_upload_requires_auth(client: TestClient) -> None:
    files = {"file": ("clip.mp4", io.BytesIO(FAKE_MP4), "video/mp4")}
    assert client.post("/api/v1/videos", files=files).status_code == 401


def test_list_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/videos").status_code == 401


# ── Upload ─────────────────────────────────────────────────────


def test_upload_creates_a_processing_video(client: TestClient) -> None:
    headers = _auth_headers(client)
    body = _upload(client, headers)

    assert body["name"] == "clip.mp4"
    assert body["size_bytes"] == len(FAKE_MP4)
    assert body["status"] == "processing"
    assert body["frames_total"] == 0
    assert body["frames_indexed"] == 0
    assert body["error"] is None
    assert "storage_key" not in body


def test_upload_strips_directory_traversal_from_name(client: TestClient) -> None:
    headers = _auth_headers(client)
    body = _upload(client, headers, name="../../etc/passwd.mp4")
    assert body["name"] == "passwd.mp4"


@pytest.mark.parametrize("name", ["clip.txt", "notes.pdf", "archive.zip", "noextension"])
def test_upload_rejects_unsupported_extensions(client: TestClient, name: str) -> None:
    headers = _auth_headers(client)
    files = {"file": (name, io.BytesIO(b"nope"), "application/octet-stream")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 415


def test_upload_rejects_files_over_the_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos import service

    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 8)
    headers = _auth_headers(client)
    files = {"file": ("big.mp4", io.BytesIO(b"\x00" * 64), "video/mp4")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 413


# ── List / get ─────────────────────────────────────────────────


def test_list_returns_only_my_videos(client: TestClient) -> None:
    mine = _auth_headers(client)
    _upload(client, mine, name="mine.mp4")

    # A second account must not see the first one's uploads.
    _auth_headers(client, email="other@example.com", name="Other Person")
    response = client.get("/api/v1/videos", headers=mine)
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 1
    assert [item["name"] for item in body["items"]] == ["mine.mp4"]


def test_list_is_newest_first(client: TestClient) -> None:
    headers = _auth_headers(client)
    _upload(client, headers, name="first.mp4")
    _upload(client, headers, name="second.mp4")

    body = client.get("/api/v1/videos", headers=headers).json()
    assert [item["name"] for item in body["items"]] == ["second.mp4", "first.mp4"]


def test_get_video_returns_metadata(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.get(f"/api/v1/videos/{video_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "clip.mp4"


def test_get_someone_elses_video_is_404(client: TestClient) -> None:
    mine = _auth_headers(client)
    video_id = _upload(client, mine)["id"]

    _auth_headers(client, email="other@example.com", name="Other Person")
    response = client.get(
        f"/api/v1/videos/{video_id}",
        headers={"Authorization": f"Bearer {_signin_other(client)}"},
    )
    assert response.status_code == 404


def _signin_other(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": SIGNUP["password"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


# ── Stream ─────────────────────────────────────────────────────


def test_stream_returns_the_file(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.get(f"/api/v1/videos/{video_id}/stream", headers=headers)
    assert response.status_code == 200
    assert response.content == FAKE_MP4
    assert response.headers["content-type"].startswith("video/")


def test_stream_plays_inline_not_as_attachment(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.get(f"/api/v1/videos/{video_id}/stream", headers=headers)
    assert "attachment" not in response.headers.get("content-disposition", "")


def test_stream_supports_range_requests(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.get(
        f"/api/v1/videos/{video_id}/stream",
        headers={**headers, "Range": "bytes=0-9"},
    )
    assert response.status_code == 206
    assert response.content == FAKE_MP4[:10]
    assert "bytes" in response.headers["content-range"]


def test_stream_someone_elses_video_is_404(client: TestClient) -> None:
    mine = _auth_headers(client)
    video_id = _upload(client, mine)["id"]
    _auth_headers(client, email="other@example.com", name="Other Person")

    response = client.get(
        f"/api/v1/videos/{video_id}/stream",
        headers={"Authorization": f"Bearer {_signin_other(client)}"},
    )
    assert response.status_code == 404


# ── Stream URL (edge worker) ───────────────────────────────────


def test_stream_url_falls_back_to_api_path_without_worker(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos import routes

    monkeypatch.setattr(routes.settings, "stream_worker_base_url", None)
    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.get(f"/api/v1/videos/{video_id}/stream-url", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["worker"] is False
    assert body["url"] == f"/api/v1/videos/{video_id}/stream"


def test_stream_url_returns_signed_worker_url_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos import streaming

    # routes and streaming both read the same cached settings singleton.
    monkeypatch.setattr(streaming.settings, "stream_worker_base_url", "https://edge.example.com")
    monkeypatch.setattr(streaming.settings, "stream_signing_secret", "secret")
    monkeypatch.setattr(streaming.settings, "stream_url_ttl_seconds", 3600)

    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.get(f"/api/v1/videos/{video_id}/stream-url", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["worker"] is True
    assert body["url"].startswith("https://edge.example.com/stream/")
    assert "expires=" in body["url"]
    assert "sig=" in body["url"]


def test_stream_url_someone_elses_video_is_404(client: TestClient) -> None:
    mine = _auth_headers(client)
    video_id = _upload(client, mine)["id"]
    _auth_headers(client, email="other@example.com", name="Other Person")

    response = client.get(
        f"/api/v1/videos/{video_id}/stream-url",
        headers={"Authorization": f"Bearer {_signin_other(client)}"},
    )
    assert response.status_code == 404


# ── Delete ─────────────────────────────────────────────────────


def test_delete_removes_the_video(client: TestClient) -> None:
    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.delete(f"/api/v1/videos/{video_id}", headers=headers)
    assert response.status_code == 200

    assert client.get(f"/api/v1/videos/{video_id}", headers=headers).status_code == 404
    body = client.get("/api/v1/videos", headers=headers).json()
    assert body["count"] == 0


def test_delete_someone_elses_video_is_404(client: TestClient) -> None:
    mine = _auth_headers(client)
    video_id = _upload(client, mine)["id"]
    _auth_headers(client, email="other@example.com", name="Other Person")

    response = client.delete(
        f"/api/v1/videos/{video_id}",
        headers={"Authorization": f"Bearer {_signin_other(client)}"},
    )
    assert response.status_code == 404
    # The original owner still has it.
    assert client.get(f"/api/v1/videos/{video_id}", headers=mine).status_code == 200
