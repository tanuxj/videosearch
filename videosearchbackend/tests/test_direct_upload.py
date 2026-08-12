"""Direct-to-storage upload flow: reserve → PUT to R2 → complete → index.

Storage is faked (tests force the local-disk backend, which cannot presign),
so these exercise the API's half of the contract: what it signs, what it
trusts, and how it reconciles uploads the client never confirms.
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.videos import service as videos_service
from tests.conftest import needs_db

settings = get_settings()

pytestmark = needs_db

SIGNUP = {"name": "Alex Rivera", "email": "alex@example.com", "password": "correct-horse-8"}


def _auth_headers(client: TestClient, **overrides: object) -> dict[str, str]:
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, **overrides})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class FakeStorage:
    """In-memory stand-in for R2: records presigns, holds object metadata."""

    supports_direct_upload = True
    backend = "r2"

    def __init__(self) -> None:
        self.objects: dict[str, int] = {}
        self.presigned: list[tuple[str, str, int]] = []
        self.deleted: list[str] = []

    def presign_put(self, key: str, content_type: str, expires_in: int) -> str:
        self.presigned.append((key, content_type, expires_in))
        return f"https://fake-r2.example/{key}?sig=fake&expires={expires_in}"

    def head(self, key: str) -> dict | None:
        if key not in self.objects:
            return None
        return {"size": self.objects[key], "content_type": "video/mp4"}

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)

    # Simulates the browser's PUT landing in the bucket.
    def put(self, key: str, size: int) -> None:
        self.objects[key] = size


@pytest.fixture()
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    storage = FakeStorage()
    monkeypatch.setattr(videos_service, "storage", storage)
    return storage


def _reserve(client: TestClient, headers: dict[str, str], **body: object) -> dict:
    payload = {"filename": "clip.mp4", "size_bytes": 1024, **body}
    response = client.post("/api/v1/videos/upload-url", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _storage_key(client: TestClient, headers: dict[str, str], video_id: str) -> str:
    """The key the API signed for this video (owner/video.ext)."""
    me = client.get("/api/v1/auth/me", headers=headers).json()
    return f"{me['id']}/{video_id}.mp4"


# ── Reserving an upload ─────────────────────────────────────────


def test_upload_url_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/videos/upload-url", json={"filename": "a.mp4", "size_bytes": 10}
    )
    assert response.status_code == 401


def test_upload_url_returns_a_presigned_put(client: TestClient, fake_storage: FakeStorage) -> None:
    headers = _auth_headers(client)
    body = _reserve(client, headers)

    assert body["direct"] is True
    assert body["method"] == "PUT"
    assert body["upload_url"].startswith("https://fake-r2.example/")
    assert body["content_type"] == "video/mp4"
    assert body["expires_in"] > 0

    key, content_type, _ = fake_storage.presigned[0]
    assert key.endswith(".mp4")
    # The signature covers the content type, so the client must be told it.
    assert content_type == body["content_type"]


def test_reserved_video_starts_pending_and_is_listed(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    headers = _auth_headers(client)
    video_id = _reserve(client, headers)["video_id"]

    body = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
    assert body["status"] == "pending"


def test_content_type_follows_the_extension(client: TestClient, fake_storage: FakeStorage) -> None:
    headers = _auth_headers(client)
    body = _reserve(client, headers, filename="holiday.mov")
    assert body["content_type"] == "video/quicktime"


def test_upload_url_rejects_unsupported_types(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/api/v1/videos/upload-url",
        headers=headers,
        json={"filename": "notes.pdf", "size_bytes": 1024},
    )
    assert response.status_code == 415


def test_upload_url_rejects_oversized_declarations(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/api/v1/videos/upload-url",
        headers=headers,
        json={"filename": "huge.mp4", "size_bytes": 600 * 1024 * 1024},
    )
    assert response.status_code == 413


def test_local_storage_reports_direct_false(client: TestClient) -> None:
    """No fake_storage fixture: the real local-disk backend cannot presign."""
    headers = _auth_headers(client)
    response = client.post(
        "/api/v1/videos/upload-url",
        headers=headers,
        json={"filename": "clip.mp4", "size_bytes": 1024},
    )
    assert response.status_code == 201
    assert response.json()["direct"] is False
    assert response.json()["upload_url"] is None


# ── Completing an upload ────────────────────────────────────────


def test_complete_fails_when_nothing_was_uploaded(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    """The client's claim is not evidence — storage is."""
    headers = _auth_headers(client)
    video_id = _reserve(client, headers)["video_id"]

    response = client.post(f"/api/v1/videos/{video_id}/complete", headers=headers)
    assert response.status_code == 409


def test_complete_promotes_to_processing(client: TestClient, fake_storage: FakeStorage) -> None:
    headers = _auth_headers(client)
    video_id = _reserve(client, headers)["video_id"]
    fake_storage.put(_storage_key(client, headers, video_id), 2048)

    response = client.post(f"/api/v1/videos/{video_id}/complete", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


def test_complete_trusts_storage_over_the_client(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    """A client that lies about size gets the real number recorded."""
    headers = _auth_headers(client)
    video_id = _reserve(client, headers, size_bytes=1)["video_id"]
    fake_storage.put(_storage_key(client, headers, video_id), 9_999)

    body = client.post(f"/api/v1/videos/{video_id}/complete", headers=headers).json()
    assert body["size_bytes"] == 9_999


def test_complete_is_not_replayable(client: TestClient, fake_storage: FakeStorage) -> None:
    headers = _auth_headers(client)
    video_id = _reserve(client, headers)["video_id"]
    fake_storage.put(_storage_key(client, headers, video_id), 2048)

    assert client.post(f"/api/v1/videos/{video_id}/complete", headers=headers).status_code == 200
    # A second call must not re-trigger indexing.
    assert client.post(f"/api/v1/videos/{video_id}/complete", headers=headers).status_code == 409


def test_complete_enforces_the_size_limit_storage_could_not(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    """A presigned PUT cannot cap the body, so the check happens here."""
    headers = _auth_headers(client)
    video_id = _reserve(client, headers, size_bytes=1024)["video_id"]
    key = _storage_key(client, headers, video_id)
    fake_storage.put(key, 600 * 1024 * 1024)

    response = client.post(f"/api/v1/videos/{video_id}/complete", headers=headers)
    assert response.status_code == 413
    # The oversized object is removed and the row with it.
    assert key in fake_storage.deleted
    assert client.get(f"/api/v1/videos/{video_id}", headers=headers).status_code == 404


def test_complete_on_someone_elses_video_is_404(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    owner = _auth_headers(client)
    video_id = _reserve(client, owner)["video_id"]
    fake_storage.put(_storage_key(client, owner, video_id), 2048)

    client.cookies.clear()
    intruder = _auth_headers(client, email="mallory@example.com")
    response = client.post(f"/api/v1/videos/{video_id}/complete", headers=intruder)
    assert response.status_code == 404


def test_complete_on_an_unknown_video_is_404(client: TestClient, fake_storage: FakeStorage) -> None:
    headers = _auth_headers(client)
    response = client.post(f"/api/v1/videos/{uuid.uuid4()}/complete", headers=headers)
    assert response.status_code == 404


# ── Sweeping abandoned uploads ──────────────────────────────────


def _sweep(older_than_minutes: int = 0) -> tuple[list[uuid.UUID], int]:
    """Run one reconcile pass on its own engine.

    Deliberately not the shared `SessionFactory`: its pool holds asyncpg
    connections created inside the TestClient's event loop, and an asyncpg
    connection cannot be used from a different loop. A private engine keeps
    this pass entirely inside the loop `asyncio.run` creates here.
    """

    async def run():
        engine = create_async_engine(settings.async_database_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                return await videos_service.sweep_pending_uploads(
                    session, older_than_minutes=older_than_minutes
                )
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_sweep_promotes_uploads_the_client_never_confirmed(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    """The closed-tab case: bytes arrived, `complete` never came."""
    headers = _auth_headers(client)
    video_id = _reserve(client, headers)["video_id"]
    fake_storage.put(_storage_key(client, headers, video_id), 4096)

    promoted, discarded = _sweep()

    assert [str(v) for v in promoted] == [video_id]
    assert discarded == 0
    body = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
    assert body["status"] == "processing"
    assert body["size_bytes"] == 4096


def test_sweep_discards_uploads_that_never_arrived(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    headers = _auth_headers(client)
    video_id = _reserve(client, headers)["video_id"]

    promoted, discarded = _sweep()

    assert promoted == []
    assert discarded == 1
    assert client.get(f"/api/v1/videos/{video_id}", headers=headers).status_code == 404


def test_sweep_leaves_fresh_pending_rows_alone(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    """A row inside the grace window may still be uploading."""
    headers = _auth_headers(client)
    video_id = _reserve(client, headers)["video_id"]

    promoted, discarded = _sweep(older_than_minutes=30)

    assert (promoted, discarded) == ([], 0)
    assert client.get(f"/api/v1/videos/{video_id}", headers=headers).json()["status"] == "pending"
