"""End-to-end tests for the collection routes.

Skipped unless TEST_DATABASE_URL points at a reachable Postgres — see
tests/conftest.py.

The rules worth pinning down here are the ones that are easy to regress:
membership is idempotent, names are unique per user but only *per user*,
deleting a collection must never delete its videos, and none of it may leak
across accounts.
"""

import io

from fastapi.testclient import TestClient

from tests.conftest import needs_db

pytestmark = needs_db

SIGNUP = {"name": "Alex Rivera", "email": "alex@example.com", "password": "correct-horse-8"}

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def _auth(client: TestClient, **overrides: object) -> tuple[dict[str, str], str]:
    """Sign up and return `(auth headers, user id)`."""
    response = client.post("/api/v1/auth/signup", json={**SIGNUP, **overrides})
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["id"]


def _upload_video(client: TestClient, headers: dict[str, str], name: str = "clip.mp4") -> str:
    files = {"file": (name, io.BytesIO(FAKE_MP4), "video/mp4")}
    response = client.post("/api/v1/videos", headers=headers, files=files)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post("/api/v1/collections", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ── Auth ───────────────────────────────────────────────────────


def test_list_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/collections").status_code == 401


def test_create_requires_auth(client: TestClient) -> None:
    assert client.post("/api/v1/collections", json={"name": "Lectures"}).status_code == 401


# ── Create / list ──────────────────────────────────────────────


def test_list_starts_empty(client: TestClient) -> None:
    headers, _ = _auth(client)
    body = client.get("/api/v1/collections", headers=headers).json()
    assert body == {"items": [], "count": 0}


def test_create_then_list(client: TestClient) -> None:
    headers, _ = _auth(client)
    _create(client, headers, "Lectures")

    body = client.get("/api/v1/collections", headers=headers).json()
    assert body["count"] == 1
    assert body["items"][0]["name"] == "Lectures"
    # A brand-new collection is empty, not absent from the list.
    assert body["items"][0]["video_count"] == 0


def test_duplicate_name_is_409(client: TestClient) -> None:
    headers, _ = _auth(client)
    _create(client, headers, "Lectures")

    response = client.post("/api/v1/collections", headers=headers, json={"name": "Lectures"})
    assert response.status_code == 409


def test_duplicate_name_is_case_insensitive(client: TestClient) -> None:
    headers, _ = _auth(client)
    _create(client, headers, "Lectures")

    response = client.post("/api/v1/collections", headers=headers, json={"name": "lectures"})
    assert response.status_code == 409


def test_same_name_allowed_for_different_users(client: TestClient) -> None:
    mine, _ = _auth(client)
    _create(client, mine, "Lectures")

    other, _ = _auth(client, email="other@example.com", name="Other Person")
    response = client.post("/api/v1/collections", headers=other, json={"name": "Lectures"})
    assert response.status_code == 201


def test_list_never_leaks_other_users_collections(client: TestClient) -> None:
    mine, _ = _auth(client)
    _create(client, mine, "Lectures")

    other, _ = _auth(client, email="other@example.com", name="Other Person")
    assert client.get("/api/v1/collections", headers=other).json()["count"] == 0


# ── Rename / delete ────────────────────────────────────────────


def test_rename(client: TestClient) -> None:
    headers, _ = _auth(client)
    collection_id = _create(client, headers, "Lectures")

    response = client.patch(
        f"/api/v1/collections/{collection_id}",
        headers=headers,
        json={"name": "Archive"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Archive"


def test_rename_onto_existing_name_is_409(client: TestClient) -> None:
    headers, _ = _auth(client)
    _create(client, headers, "Lectures")
    second = _create(client, headers, "Demos")

    response = client.patch(
        f"/api/v1/collections/{second}", headers=headers, json={"name": "Lectures"}
    )
    assert response.status_code == 409


def test_rename_someone_elses_collection_is_404(client: TestClient) -> None:
    mine, _ = _auth(client)
    collection_id = _create(client, mine, "Lectures")
    other, _ = _auth(client, email="other@example.com", name="Other Person")

    response = client.patch(
        f"/api/v1/collections/{collection_id}", headers=other, json={"name": "Stolen"}
    )
    assert response.status_code == 404


def test_delete_collection_keeps_its_videos(client: TestClient) -> None:
    """The whole point of the cascade rules: unfiling is not deleting."""
    headers, _ = _auth(client)
    video_id = _upload_video(client, headers)
    collection_id = _create(client, headers, "Lectures")
    client.post(
        f"/api/v1/collections/{collection_id}/videos",
        headers=headers,
        json={"video_ids": [video_id]},
    )

    assert client.delete(f"/api/v1/collections/{collection_id}", headers=headers).status_code == 200

    # The video survived, and no longer claims a collection.
    body = client.get("/api/v1/videos", headers=headers).json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == video_id
    assert body["items"][0]["collection_ids"] == []


def test_delete_someone_elses_collection_is_404(client: TestClient) -> None:
    mine, _ = _auth(client)
    collection_id = _create(client, mine, "Lectures")
    other, _ = _auth(client, email="other@example.com", name="Other Person")

    assert client.delete(f"/api/v1/collections/{collection_id}", headers=other).status_code == 404
    assert client.get("/api/v1/collections", headers=mine).json()["count"] == 1


# ── Membership ─────────────────────────────────────────────────


def test_add_videos_and_see_them_on_the_list(client: TestClient) -> None:
    headers, _ = _auth(client)
    video_id = _upload_video(client, headers)
    collection_id = _create(client, headers, "Lectures")

    response = client.post(
        f"/api/v1/collections/{collection_id}/videos",
        headers=headers,
        json={"video_ids": [video_id]},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 1

    body = client.get("/api/v1/videos", headers=headers).json()
    assert body["items"][0]["collection_ids"] == [collection_id]
    assert client.get("/api/v1/collections", headers=headers).json()["items"][0]["video_count"] == 1


def test_add_is_idempotent(client: TestClient) -> None:
    headers, _ = _auth(client)
    video_id = _upload_video(client, headers)
    collection_id = _create(client, headers, "Lectures")
    payload = {"video_ids": [video_id]}

    client.post(f"/api/v1/collections/{collection_id}/videos", headers=headers, json=payload)
    second = client.post(
        f"/api/v1/collections/{collection_id}/videos", headers=headers, json=payload
    )
    assert second.status_code == 200

    # Re-adding must not double-count the membership.
    body = client.get("/api/v1/collections", headers=headers).json()
    assert body["items"][0]["video_count"] == 1


def test_add_skips_videos_you_dont_own(client: TestClient) -> None:
    mine, _ = _auth(client)
    other, _ = _auth(client, email="other@example.com", name="Other Person")
    theirs = _upload_video(client, other)
    collection_id = _create(client, mine, "Lectures")

    response = client.post(
        f"/api/v1/collections/{collection_id}/videos",
        headers=mine,
        json={"video_ids": [theirs]},
    )
    # Skipped, not rejected — and nothing was filed.
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_a_video_can_be_in_several_collections(client: TestClient) -> None:
    headers, _ = _auth(client)
    video_id = _upload_video(client, headers)
    first = _create(client, headers, "Lectures")
    second = _create(client, headers, "To review")

    for collection_id in (first, second):
        client.post(
            f"/api/v1/collections/{collection_id}/videos",
            headers=headers,
            json={"video_ids": [video_id]},
        )

    body = client.get("/api/v1/videos", headers=headers).json()
    assert sorted(body["items"][0]["collection_ids"]) == sorted([first, second])


def test_remove_videos(client: TestClient) -> None:
    headers, _ = _auth(client)
    video_id = _upload_video(client, headers)
    collection_id = _create(client, headers, "Lectures")
    payload = {"video_ids": [video_id]}
    client.post(f"/api/v1/collections/{collection_id}/videos", headers=headers, json=payload)

    response = client.post(
        f"/api/v1/collections/{collection_id}/videos/remove", headers=headers, json=payload
    )
    assert response.status_code == 200
    assert response.json()["count"] == 1

    # Unfiled, but still in the library.
    body = client.get("/api/v1/videos", headers=headers).json()
    assert body["count"] == 1
    assert body["items"][0]["collection_ids"] == []


def test_add_to_someone_elses_collection_is_404(client: TestClient) -> None:
    mine, _ = _auth(client)
    video_id = _upload_video(client, mine)
    other, _ = _auth(client, email="other@example.com", name="Other Person")
    theirs = _create(client, other, "Lectures")

    response = client.post(
        f"/api/v1/collections/{theirs}/videos", headers=mine, json={"video_ids": [video_id]}
    )
    assert response.status_code == 404


# ── Filtering the video list ───────────────────────────────────


def test_filter_videos_by_collection(client: TestClient) -> None:
    headers, _ = _auth(client)
    filed = _upload_video(client, headers, "filed.mp4")
    _upload_video(client, headers, "loose.mp4")
    collection_id = _create(client, headers, "Lectures")
    client.post(
        f"/api/v1/collections/{collection_id}/videos",
        headers=headers,
        json={"video_ids": [filed]},
    )

    assert client.get("/api/v1/videos", headers=headers).json()["count"] == 2

    body = client.get(f"/api/v1/videos?collection_id={collection_id}", headers=headers).json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == filed


def test_filter_by_someone_elses_collection_is_empty(client: TestClient) -> None:
    """A leaked collection id must not widen the caller's own library."""
    mine, _ = _auth(client)
    _upload_video(client, mine)
    other, _ = _auth(client, email="other@example.com", name="Other Person")
    theirs = _create(client, other, "Lectures")

    body = client.get(f"/api/v1/videos?collection_id={theirs}", headers=mine).json()
    assert body["count"] == 0


def test_memberships_cascade_when_video_deleted(client: TestClient) -> None:
    headers, _ = _auth(client)
    video_id = _upload_video(client, headers)
    collection_id = _create(client, headers, "Lectures")
    client.post(
        f"/api/v1/collections/{collection_id}/videos",
        headers=headers,
        json={"video_ids": [video_id]},
    )

    assert client.delete(f"/api/v1/videos/{video_id}", headers=headers).status_code == 200

    # The collection outlives the video, now empty rather than holding a
    # dangling membership row. `video_count` is computed by joining
    # `collection_videos`, so a zero here *is* the proof the row cascaded away
    # — no direct table read needed.
    body = client.get("/api/v1/collections", headers=headers).json()
    assert body["count"] == 1
    assert body["items"][0]["video_count"] == 0
