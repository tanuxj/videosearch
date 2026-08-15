"""End-to-end tests for the video routes.

Skipped unless TEST_DATABASE_URL points at a reachable Postgres — see
tests/conftest.py. Storage is forced to the local disk backend, so these
tests never touch a real R2 bucket.
"""

import io
import math

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
    source: str | None = None,
) -> dict:
    files = {"file": (name, io.BytesIO(content), "video/mp4")}
    data = {"source": source} if source is not None else None
    response = client.post("/api/v1/videos", headers=headers, files=files, data=data)
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


def test_upload_defaults_to_source_upload(client: TestClient) -> None:
    headers = _auth_headers(client)
    assert _upload(client, headers)["source"] == "upload"


def test_upload_tags_recordings(client: TestClient) -> None:
    headers = _auth_headers(client)
    body = _upload(client, headers, source="recording")
    assert body["source"] == "recording"

    # The tag survives the round trip through the list endpoint.
    listing = client.get("/api/v1/videos", headers=headers).json()
    assert [item["source"] for item in listing["items"]] == ["recording"]


def test_upload_unknown_source_falls_back_to_upload(client: TestClient) -> None:
    # A stale client sending an unknown label must not 500 on the check
    # constraint — it degrades to a plain upload instead.
    headers = _auth_headers(client)
    body = _upload(client, headers, source="mystery")
    assert body["source"] == "upload"


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


# ── Clip download ──────────────────────────────────────────────


def test_clip_requires_auth(client: TestClient) -> None:
    response = client.get(
        "/api/v1/videos/00000000-0000-0000-0000-000000000000/clip",
        params={"start": 0, "end": 1},
    )
    assert response.status_code == 401


def test_clip_someone_elses_video_is_404(client: TestClient) -> None:
    mine = _auth_headers(client)
    video_id = _upload(client, mine)["id"]
    _auth_headers(client, email="other@example.com", name="Other Person")

    response = client.get(
        f"/api/v1/videos/{video_id}/clip",
        headers={"Authorization": f"Bearer {_signin_other(client)}"},
        params={"start": 0, "end": 1},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (0, 0),
        (5, 3),
        (0, -1),
        (-1, 5),
        (0, 10_000),  # over the MAX_CLIP_SECONDS cap
    ],
)
def test_clip_rejects_invalid_ranges(client: TestClient, start: float, end: float) -> None:
    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.get(
        f"/api/v1/videos/{video_id}/clip",
        headers=headers,
        params={"start": start, "end": end},
    )
    assert response.status_code == 422


def test_clip_clamps_end_to_known_duration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from app.videos import clips, service

    trimmed: list[tuple] = []

    def _fake_trim(source, start, end, output):
        trimmed.append((start, end))
        output.write_bytes(b"fake-clip-mp4-bytes")
        return output

    monkeypatch.setattr(clips, "trim", _fake_trim)
    headers = _auth_headers(client)

    async def _fake_get_video(db, owner_id, video_id):
        # A known duration exercises the end-clamp without touching the DB.
        return SimpleNamespace(
            storage_key="00000000-0000-0000-0000-000000000000/video.mp4",
            name="clip.mp4",
            duration_seconds=10.0,
        )

    monkeypatch.setattr(service, "get_video", _fake_get_video)

    response = client.get(
        "/api/v1/videos/00000000-0000-0000-0000-000000000000/clip",
        headers=headers,
        params={"start": 2, "end": 999},
    )
    assert response.status_code == 200, response.text
    assert response.content == b"fake-clip-mp4-bytes"
    assert "attachment" in response.headers.get("content-disposition", "")
    assert trimmed == [(2.0, 10.0)]


def test_clip_returns_trimmed_attachment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos import clips

    def _fake_trim(source, start, end, output):
        output.write_bytes(b"fake-clip-mp4-bytes")
        return output

    monkeypatch.setattr(clips, "trim", _fake_trim)
    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.get(
        f"/api/v1/videos/{video_id}/clip",
        headers=headers,
        params={"start": 1.5, "end": 4.5},
    )
    assert response.status_code == 200, response.text
    assert response.content == b"fake-clip-mp4-bytes"
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    # Starlette URL-encodes the filename (spaces/brackets) in the `filename*=`
    # form; decode it back before comparing. The name is the video's stem
    # ("clip.mp4" → "clip") so the download reads like a real clip file.
    from urllib.parse import unquote

    assert unquote(disposition) == "attachment; filename*=utf-8''clip [1-4s].mp4"
    assert response.headers["content-type"].startswith("video/mp4")


def test_clip_503_when_trim_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.videos import clips

    def _broken_trim(source, start, end, output):
        raise clips.ClipError("boom")

    monkeypatch.setattr(clips, "trim", _broken_trim)
    headers = _auth_headers(client)
    video_id = _upload(client, headers)["id"]

    response = client.get(
        f"/api/v1/videos/{video_id}/clip",
        headers=headers,
        params={"start": 0, "end": 2},
    )
    assert response.status_code == 503
    assert "boom" in response.json()["detail"]


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


# ── Presigned direct upload ───────────────────────────────────────


class _FakeS3:
    """Minimal boto3 stand-in so presign/multipart/complete can be tested without R2."""

    def __init__(self, *, content_length: int | None = None) -> None:
        self._content_length = content_length
        self.last_generated: tuple | None = None
        self.multipart: dict | None = None
        self.completed: list[tuple] = []
        self.aborted: list[tuple] = []

    def generate_presigned_url(self, method: str, Params: dict, ExpiresIn: int) -> str:
        self.last_generated = (method, Params, ExpiresIn)
        return "https://upload.example.com/fake?sig=abc"

    def create_multipart_upload(self, Bucket: str, Key: str, ContentType: str) -> dict:
        self.multipart = {"Bucket": Bucket, "Key": Key, "ContentType": ContentType}
        return {"UploadId": "fake-upload-id"}

    def complete_multipart_upload(
        self, Bucket: str, Key: str, UploadId: str, MultipartUpload: dict
    ) -> dict:
        self.completed.append((Bucket, Key, UploadId, MultipartUpload))
        return {"Location": "https://upload.example.com/fake-object"}

    def abort_multipart_upload(self, Bucket: str, Key: str, UploadId: str) -> dict:
        self.aborted.append((Bucket, Key, UploadId))
        return {}

    def delete_object(self, Bucket: str, Key: str) -> dict:
        return {}

    def head_object(self, Bucket: str, Key: str) -> dict:
        if self._content_length is None:
            from botocore.exceptions import ClientError

            raise ClientError(
                {
                    "Error": {"Code": "404"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "HeadObject",
            )
        return {"ContentLength": self._content_length}


def _enable_presign(
    monkeypatch: pytest.MonkeyPatch,
    storage_module,
    *,
    content_length: int | None = None,
) -> _FakeS3:
    """Make the storage singleton look like an R2 backend for one test."""
    fake = _FakeS3(content_length=content_length)
    monkeypatch.setattr(storage_module, "_client", fake)
    monkeypatch.setattr(storage_module, "_bucket", "test-bucket")
    return fake


def test_presign_rejected_when_storage_cannot_presign(client: TestClient) -> None:
    # Local storage backend (test default) has no presigned URLs.
    headers = _auth_headers(client)
    response = client.post(
        "/api/v1/videos/presign",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    )
    assert response.status_code == 409
    assert "multipart" in response.json()["detail"]


def test_presign_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/videos/presign",
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    )
    assert response.status_code == 401


def test_presign_tags_recordings(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.videos.storage import storage

    _enable_presign(monkeypatch, storage)
    headers = _auth_headers(client)

    response = client.post(
        "/api/v1/videos/presign",
        headers=headers,
        json={
            "filename": "clip.mp4",
            "size_bytes": len(FAKE_MP4),
            "source": "recording",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["video"]["source"] == "recording"


def test_presign_rejects_unknown_source(client: TestClient) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/api/v1/videos/presign",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4), "source": "mystery"},
    )
    # The schema whitelists the value, so a typo'd label fails fast.
    assert response.status_code == 422


@pytest.mark.parametrize("name", ["clip.txt", "notes.pdf"])
def test_presign_rejects_unsupported_extensions(client: TestClient, name: str) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/api/v1/videos/presign",
        headers=headers,
        json={"filename": name, "size_bytes": 8},
    )
    assert response.status_code == 415


def test_presign_reserves_video_and_returns_upload_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid as uuid_mod

    from app.videos.storage import storage

    fake = _enable_presign(monkeypatch, storage)
    # Sign up directly so we know the owner id the key must be scoped to.
    signup = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Key Owner",
            "email": "key.owner@example.com",
            "password": SIGNUP["password"],
        },
    )
    owner_id = signup.json()["user"]["id"]
    token = signup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/videos/presign",
        headers=headers,
        json={
            "filename": "clip.mp4",
            "size_bytes": len(FAKE_MP4),
            "content_type": "video/mp4",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["upload_url"] == "https://upload.example.com/fake?sig=abc"
    assert body["expires_in"] > 0
    assert body["video"]["status"] == "processing"
    assert body["video"]["name"] == "clip.mp4"
    assert body["video"]["size_bytes"] == len(FAKE_MP4)
    # Default source unless the client says otherwise.
    assert body["video"]["source"] == "upload"

    # The URL was minted for the object key the row owns: scoped to the
    # owner's id, `.mp4` suffix, and both path segments are valid UUIDs —
    # not something a client can inject into the bucket layout.
    method, params, _ = fake.last_generated
    assert method == "put_object"
    assert params["ContentType"] == "video/mp4"
    owner_part, video_file = params["Key"].split("/")
    assert video_file.endswith(".mp4")
    assert str(uuid_mod.UUID(owner_part)) == owner_id
    # The per-video part is a fresh UUID (may differ from the row id — the
    # key is opaque, the row stores it).
    uuid_mod.UUID(video_file.removesuffix(".mp4"))

    # The row exists server-side and shows in the user's list.
    listing = client.get("/api/v1/videos", headers=headers).json()
    assert [item["id"] for item in listing["items"]] == [body["video"]["id"]]


def test_complete_confirms_upload_and_starts_indexing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos import pipeline, routes
    from app.videos.storage import storage

    _enable_presign(monkeypatch, storage, content_length=len(FAKE_MP4))
    # Tests run with INDEX_ON_UPLOAD=false; this test exercises the indexing
    # trigger, so turn it on just for the route under test.
    monkeypatch.setattr(routes.settings, "index_on_upload", True)
    started: list = []
    monkeypatch.setattr(
        pipeline,
        "index_video",
        lambda video_id, source_path=None: started.append(video_id),
    )
    headers = _auth_headers(client)

    reserved = client.post(
        "/api/v1/videos/presign",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    ).json()
    video_id = reserved["video"]["id"]

    response = client.post(f"/api/v1/videos/{video_id}/complete", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["video"]["id"] == video_id
    assert body["video"]["status"] == "processing"
    assert "indexing" in body["message"].lower()
    # The pipeline was handed the video id (background task consumed it).
    # `started` collects UUID objects; compare string forms.
    assert [str(item) for item in started] == [video_id]


def test_complete_409_when_file_never_uploaded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos.storage import storage

    _enable_presign(monkeypatch, storage)
    headers = _auth_headers(client)
    video_id = client.post(
        "/api/v1/videos/presign",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    ).json()["video"]["id"]

    response = client.post(f"/api/v1/videos/{video_id}/complete", headers=headers)
    assert response.status_code == 409
    assert "not been uploaded" in response.json()["detail"]


def test_complete_409_on_size_mismatch(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.videos.storage import storage

    # Storage reports a different size than what was declared at presign.
    _enable_presign(monkeypatch, storage, content_length=999)
    headers = _auth_headers(client)
    video_id = client.post(
        "/api/v1/videos/presign",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    ).json()["video"]["id"]

    response = client.post(f"/api/v1/videos/{video_id}/complete", headers=headers)
    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]


def test_complete_someone_elses_video_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos.storage import storage

    _enable_presign(monkeypatch, storage, content_length=len(FAKE_MP4))
    mine = _auth_headers(client)
    video_id = client.post(
        "/api/v1/videos/presign",
        headers=mine,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    ).json()["video"]["id"]
    _auth_headers(client, email="other@example.com", name="Other Person")

    response = client.post(
        f"/api/v1/videos/{video_id}/complete",
        headers={"Authorization": f"Bearer {_signin_other(client)}"},
    )
    assert response.status_code == 404


# ── Presigned multipart upload (large files) ───────────────────


def test_presign_multipart_reserves_video_and_returns_part_urls(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos.storage import storage

    fake = _enable_presign(monkeypatch, storage)
    headers = _auth_headers(client)

    # 6 GiB — above the 5 GiB single-PUT cap, so it exercises chunk planning.
    size_bytes = 6 * 1024 * 1024 * 1024
    response = client.post(
        "/api/v1/videos/presign/multipart",
        headers=headers,
        json={"filename": "big.mp4", "size_bytes": size_bytes, "content_type": "video/mp4"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["upload_id"] == "fake-upload-id"
    assert body["video"]["status"] == "processing"
    assert body["video"]["size_bytes"] == size_bytes
    assert body["expires_in"] > 0

    # Chunk plan: every non-final chunk is ≥ 5 MiB and there are ≤ 1000 chunks.
    part_size = body["part_size"]
    assert part_size >= 5 * 1024 * 1024
    assert len(body["parts"]) == math.ceil(size_bytes / part_size)
    assert len(body["parts"]) <= 1000
    assert body["parts"][0]["part_number"] == 1
    assert body["parts"][0]["url"].startswith("https://")
    expected_numbers = list(range(1, len(body["parts"]) + 1))
    assert [part["part_number"] for part in body["parts"]] == expected_numbers

    # The multipart upload was opened against the row's object key.
    assert fake.multipart["Key"].endswith(".mp4")
    assert fake.multipart["ContentType"] == "video/mp4"

    listing = client.get("/api/v1/videos", headers=headers).json()
    assert [item["id"] for item in listing["items"]] == [body["video"]["id"]]


def test_presign_multipart_small_file_gets_one_part(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos.storage import storage

    _enable_presign(monkeypatch, storage)
    headers = _auth_headers(client)

    response = client.post(
        "/api/v1/videos/presign/multipart",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["parts"]) == 1
    assert body["part_size"] >= 5 * 1024 * 1024


def test_presign_multipart_rejected_when_storage_cannot_presign(
    client: TestClient,
) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/api/v1/videos/presign/multipart",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    )
    assert response.status_code == 409
    assert "multipart" in response.json()["detail"]


def test_presign_multipart_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/videos/presign/multipart",
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    )
    assert response.status_code == 401


def test_presign_multipart_rejects_oversize(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos import service
    from app.videos.storage import storage

    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 8)
    _enable_presign(monkeypatch, storage)
    headers = _auth_headers(client)

    response = client.post(
        "/api/v1/videos/presign/multipart",
        headers=headers,
        json={"filename": "big.mp4", "size_bytes": 64},
    )
    assert response.status_code == 413


def test_presign_multipart_cleans_up_when_part_urls_fail(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import ClientError

    from app.videos.storage import storage

    fake = _enable_presign(monkeypatch, storage)

    def _explode(method: str, Params: dict, ExpiresIn: int) -> str:
        if method == "upload_part":
            raise ClientError(
                {"Error": {"Code": "InternalError"}, "ResponseMetadata": {"HTTPStatusCode": 500}},
                "GeneratePresignedUrl",
            )
        return "https://upload.example.com/fake?sig=abc"

    fake.generate_presigned_url = _explode
    headers = _auth_headers(client)

    with pytest.raises(ClientError):
        client.post(
            "/api/v1/videos/presign/multipart",
            headers=headers,
            json={"filename": "big.mp4", "size_bytes": 6 * 1024 * 1024 * 1024},
        )

    # The multipart upload was aborted and the reserved row removed.
    assert fake.aborted and fake.aborted[0][2] == "fake-upload-id"
    assert client.get("/api/v1/videos", headers=headers).json()["count"] == 0


def test_complete_multipart_confirms_and_starts_indexing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos import pipeline, routes
    from app.videos.storage import storage

    fake = _enable_presign(monkeypatch, storage, content_length=len(FAKE_MP4))
    monkeypatch.setattr(routes.settings, "index_on_upload", True)
    started: list = []
    monkeypatch.setattr(
        pipeline,
        "index_video",
        lambda video_id, source_path=None: started.append(video_id),
    )
    headers = _auth_headers(client)

    reserved = client.post(
        "/api/v1/videos/presign/multipart",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    ).json()
    video_id = reserved["video"]["id"]

    response = client.post(
        f"/api/v1/videos/{video_id}/complete/multipart",
        headers=headers,
        json={"upload_id": "fake-upload-id", "parts": [{"part_number": 1, "etag": '"abc123"'}]},
    )
    assert response.status_code == 200, response.text
    assert "indexing" in response.json()["message"].lower()

    # Parts were assembled in order, then the object size was verified.
    assert fake.completed[0][2] == "fake-upload-id"
    assert fake.completed[0][3]["Parts"] == [{"PartNumber": 1, "ETag": '"abc123"'}]
    assert [str(item) for item in started] == [video_id]


def test_complete_multipart_409_on_size_mismatch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos.storage import storage

    _enable_presign(monkeypatch, storage, content_length=999)
    headers = _auth_headers(client)
    video_id = client.post(
        "/api/v1/videos/presign/multipart",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    ).json()["video"]["id"]

    response = client.post(
        f"/api/v1/videos/{video_id}/complete/multipart",
        headers=headers,
        json={"upload_id": "fake-upload-id", "parts": [{"part_number": 1, "etag": '"x"'}]},
    )
    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]


def test_complete_multipart_409_when_parts_fail_to_assemble(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos.storage import storage

    _enable_presign(monkeypatch, storage, content_length=len(FAKE_MP4))
    monkeypatch.setattr(
        storage,
        "complete_multipart",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("InvalidPart")),
    )
    headers = _auth_headers(client)
    video_id = client.post(
        "/api/v1/videos/presign/multipart",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    ).json()["video"]["id"]

    response = client.post(
        f"/api/v1/videos/{video_id}/complete/multipart",
        headers=headers,
        json={"upload_id": "fake-upload-id", "parts": [{"part_number": 1, "etag": '"x"'}]},
    )
    assert response.status_code == 409
    assert "Could not assemble" in response.json()["detail"]


def test_complete_multipart_someone_elses_video_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.videos.storage import storage

    _enable_presign(monkeypatch, storage, content_length=len(FAKE_MP4))
    mine = _auth_headers(client)
    video_id = client.post(
        "/api/v1/videos/presign/multipart",
        headers=mine,
        json={"filename": "clip.mp4", "size_bytes": len(FAKE_MP4)},
    ).json()["video"]["id"]
    _auth_headers(client, email="other@example.com", name="Other Person")

    response = client.post(
        f"/api/v1/videos/{video_id}/complete/multipart",
        headers={"Authorization": f"Bearer {_signin_other(client)}"},
        json={"upload_id": "fake-upload-id", "parts": [{"part_number": 1, "etag": '"x"'}]},
    )
    assert response.status_code == 404
