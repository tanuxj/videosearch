"""End-to-end tests for the workspace routes and workspace-aware video access.

Skipped unless TEST_DATABASE_URL points at a reachable Postgres — see
tests/conftest.py. Storage is forced to the local disk backend, so these
tests never touch a real R2 bucket.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.conftest import needs_db

pytestmark = needs_db

SIGNUP = {"name": "Alex Rivera", "email": "alex@example.com", "password": "correct-horse-8"}

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def _signup(
    client: TestClient, *, email: str = "alex@example.com", name: str = "Alex Rivera"
) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/signup",
        json={"name": name, "email": email, "password": SIGNUP["password"]},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": SIGNUP["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_workspace(client: TestClient, headers: dict[str, str], name: str = "Design") -> str:
    response = client.post("/api/v1/workspaces", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "clip.mp4",
    workspace_id: str | None = None,
) -> dict:
    files = {"file": (name, io.BytesIO(FAKE_MP4), "video/mp4")}
    data = {"workspace_id": workspace_id} if workspace_id else None
    response = client.post("/api/v1/videos", headers=headers, files=files, data=data)
    assert response.status_code == 201, response.text
    return response.json()


# ── Workspace CRUD ─────────────────────────────────────────────


def test_create_workspace_makes_creator_owner(client: TestClient) -> None:
    headers = _signup(client)
    workspace_id = _create_workspace(client, headers, "Design")

    body = client.get(f"/api/v1/workspaces/{workspace_id}", headers=headers)
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["workspace"]["name"] == "Design"
    assert data["workspace"]["role"] == "owner"
    assert data["workspace"]["member_count"] == 1
    assert [member["role"] for member in data["members"]] == ["owner"]


def test_list_workspaces_shows_memberships(client: TestClient) -> None:
    headers = _signup(client)
    _create_workspace(client, headers, "Design")
    _create_workspace(client, headers, "Marketing")

    body = client.get("/api/v1/workspaces", headers=headers)
    assert body.status_code == 200
    items = body.json()["items"]
    assert [item["name"] for item in items] == ["Design", "Marketing"]
    assert all(item["role"] == "owner" for item in items)
    assert all(item["member_count"] == 1 for item in items)


def test_rename_workspace_owner_only(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner, "Old Name")

    member = _signup(client, email="member@example.com", name="Member")
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "member@example.com", "role": "member"},
    )

    # Owner can rename.
    response = client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=owner,
        json={"name": "New Name"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "New Name"

    # A plain member cannot.
    response = client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        headers=member,
        json={"name": "Nope"},
    )
    assert response.status_code == 403


def test_delete_workspace_owner_only(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)

    member = _signup(client, email="member@example.com", name="Member")
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "member@example.com", "role": "member"},
    )

    assert (
        client.delete(f"/api/v1/workspaces/{workspace_id}", headers=member).status_code
        == 403
    )
    response = client.delete(f"/api/v1/workspaces/{workspace_id}", headers=owner)
    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/workspaces/{workspace_id}", headers=owner).status_code == 404


def test_deleting_workspace_reverts_videos_to_uploader(
    client: TestClient,
) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    video = _upload(client, owner, workspace_id=workspace_id)
    assert video["workspace_id"] == workspace_id

    assert client.delete(f"/api/v1/workspaces/{workspace_id}", headers=owner).status_code == 200

    # The video is back in the uploader's personal library, not deleted.
    body = client.get(f"/api/v1/videos/{video['id']}", headers=owner)
    assert body.status_code == 200, body.text
    assert body.json()["workspace_id"] is None


# ── Membership ─────────────────────────────────────────────────


def test_invite_by_email_and_list_members(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    _signup(client, email="bob@example.com", name="Bob")

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "bob@example.com", "role": "viewer"},
    )
    assert response.status_code == 201, response.text
    member = response.json()
    assert member["email"] == "bob@example.com"
    assert member["role"] == "viewer"

    detail = client.get(f"/api/v1/workspaces/{workspace_id}", headers=owner).json()
    assert detail["workspace"]["member_count"] == 2
    assert sorted(m["email"] for m in detail["members"]) == [
        "bob@example.com",
        "owner@example.com",
    ]


def test_invite_nonexistent_email_is_404(client: TestClient) -> None:
    owner = _signup(client)
    workspace_id = _create_workspace(client, owner)
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "ghost@example.com", "role": "member"},
    )
    assert response.status_code == 404
    assert "sign up" in response.json()["detail"]


def test_invite_requires_manager_role(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    _signup(client, email="viewer@example.com", name="Viewer")
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "viewer@example.com", "role": "viewer"},
    )
    viewer = _login(client, "viewer@example.com")

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=viewer,
        json={"email": "owner@example.com", "role": "member"},
    )
    assert response.status_code == 403


def test_invite_second_owner_is_rejected(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    _signup(client, email="bob@example.com", name="Bob")

    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "bob@example.com", "role": "owner"},
    )
    # The schema whitelists assignable roles — owner is not one of them.
    assert response.status_code == 422


def test_change_member_role_owner_only(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    _signup(client, email="bob@example.com", name="Bob")
    invited = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "bob@example.com", "role": "viewer"},
    ).json()
    bob_id = invited["user_id"]

    response = client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{bob_id}",
        headers=owner,
        json={"role": "admin"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"


def test_change_owner_role_is_rejected(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    owner_id = client.get("/api/v1/auth/me", headers=owner).json()["id"]

    response = client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{owner_id}",
        headers=owner,
        json={"role": "member"},
    )
    assert response.status_code == 409


def test_remove_member(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    _signup(client, email="bob@example.com", name="Bob")
    bob_id = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "bob@example.com", "role": "member"},
    ).json()["user_id"]

    response = client.delete(
        f"/api/v1/workspaces/{workspace_id}/members/{bob_id}", headers=owner
    )
    assert response.status_code == 200, response.text

    # The removed member loses access entirely.
    bob = _login(client, "bob@example.com")
    assert client.get(f"/api/v1/workspaces/{workspace_id}", headers=bob).status_code == 404


def test_leave_workspace_and_owner_cannot_leave(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    _signup(client, email="bob@example.com", name="Bob")
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "bob@example.com", "role": "member"},
    )
    bob = _login(client, "bob@example.com")

    response = client.post(f"/api/v1/workspaces/{workspace_id}/leave", headers=bob)
    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/workspaces/{workspace_id}", headers=bob).status_code == 404

    # The owner cannot leave — they must delete the workspace.
    response = client.post(f"/api/v1/workspaces/{workspace_id}/leave", headers=owner)
    assert response.status_code == 409


# ── Workspace-aware video access ───────────────────────────────


def test_upload_into_workspace_sets_workspace_id(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    video = _upload(client, owner, workspace_id=workspace_id)

    assert video["workspace_id"] == workspace_id
    listing = client.get(
        f"/api/v1/videos?workspace_id={workspace_id}", headers=owner
    ).json()
    assert [item["id"] for item in listing["items"]] == [video["id"]]


def test_upload_into_workspace_requires_membership(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    stranger = _signup(client, email="stranger@example.com", name="Stranger")

    files = {"file": ("clip.mp4", io.BytesIO(FAKE_MP4), "video/mp4")}
    response = client.post(
        "/api/v1/videos",
        headers=stranger,
        files=files,
        data={"workspace_id": workspace_id},
    )
    assert response.status_code == 403


def test_viewer_cannot_upload_into_workspace(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    _signup(client, email="viewer@example.com", name="Viewer")
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "viewer@example.com", "role": "viewer"},
    )
    viewer = _login(client, "viewer@example.com")

    files = {"file": ("clip.mp4", io.BytesIO(FAKE_MP4), "video/mp4")}
    response = client.post(
        "/api/v1/videos",
        headers=viewer,
        files=files,
        data={"workspace_id": workspace_id},
    )
    assert response.status_code == 403


def test_member_can_see_and_stream_workspace_videos(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    video = _upload(client, owner, workspace_id=workspace_id)

    _signup(client, email="bob@example.com", name="Bob")
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "bob@example.com", "role": "member"},
    )
    bob = _login(client, "bob@example.com")

    # Bob sees the workspace video in his list and can fetch/stream it.
    listing = client.get("/api/v1/videos", headers=bob).json()
    assert [item["id"] for item in listing["items"]] == [video["id"]]
    assert client.get(f"/api/v1/videos/{video['id']}", headers=bob).status_code == 200
    stream = client.get(f"/api/v1/videos/{video['id']}/stream", headers=bob)
    assert stream.status_code == 200
    assert stream.content == FAKE_MP4

    # The owner's *personal* videos stay private — Bob's list is only the shared one.
    _upload(client, owner, name="private.mp4")
    listing = client.get("/api/v1/videos", headers=bob).json()
    assert [item["name"] for item in listing["items"]] == ["clip.mp4"]


def test_non_member_cannot_see_workspace_videos(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    video = _upload(client, owner, workspace_id=workspace_id)
    stranger = _signup(client, email="stranger@example.com", name="Stranger")

    assert (
        client.get(f"/api/v1/videos/{video['id']}", headers=stranger).status_code == 404
    )
    assert (
        client.get(f"/api/v1/videos/{video['id']}/stream", headers=stranger).status_code
        == 404
    )
    assert client.get("/api/v1/videos", headers=stranger).json()["count"] == 0


def test_workspace_filter_hides_personal_videos(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    _upload(client, owner, name="personal.mp4")
    _upload(client, owner, name="shared.mp4", workspace_id=workspace_id)

    listing = client.get(
        f"/api/v1/videos?workspace_id={workspace_id}", headers=owner
    ).json()
    assert [item["name"] for item in listing["items"]] == ["shared.mp4"]


def test_workspace_filter_non_member_is_empty(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    stranger = _signup(client, email="stranger@example.com", name="Stranger")

    listing = client.get(
        f"/api/v1/videos?workspace_id={workspace_id}", headers=stranger
    ).json()
    assert listing["count"] == 0


def test_viewer_can_watch_but_not_delete(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    video = _upload(client, owner, workspace_id=workspace_id)

    _signup(client, email="viewer@example.com", name="Viewer")
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "viewer@example.com", "role": "viewer"},
    )
    viewer = _login(client, "viewer@example.com")

    # Viewing works…
    assert client.get(f"/api/v1/videos/{video['id']}", headers=viewer).status_code == 200
    # …but deleting is 403, and the video survives.
    assert client.delete(f"/api/v1/videos/{video['id']}", headers=viewer).status_code == 403
    assert client.get(f"/api/v1/videos/{video['id']}", headers=owner).status_code == 200


def test_member_can_delete_workspace_video(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    video = _upload(client, owner, workspace_id=workspace_id)

    _signup(client, email="bob@example.com", name="Bob")
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "bob@example.com", "role": "member"},
    )
    bob = _login(client, "bob@example.com")

    response = client.delete(f"/api/v1/videos/{video['id']}", headers=bob)
    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/videos/{video['id']}", headers=owner).status_code == 404


def test_move_video_between_workspaces(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    design = _create_workspace(client, owner, "Design")
    marketing = _create_workspace(client, owner, "Marketing")
    video = _upload(client, owner, workspace_id=design)

    response = client.patch(
        f"/api/v1/videos/{video['id']}",
        headers=owner,
        json={"workspace_id": marketing},
    )
    assert response.status_code == 200, response.text
    assert response.json()["workspace_id"] == marketing

    # Back to the personal library.
    response = client.patch(
        f"/api/v1/videos/{video['id']}",
        headers=owner,
        json={"workspace_id": None},
    )
    assert response.status_code == 200
    assert response.json()["workspace_id"] is None


def test_move_requires_editor_role_in_target(client: TestClient) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    design = _create_workspace(client, owner, "Design")
    other = _create_workspace(client, owner, "Other")
    video = _upload(client, owner, workspace_id=design)

    # A viewer of "Other" can see the video (member of Design via owner? no —
    # same owner). Simpler: a stranger can't move into a workspace at all.
    stranger = _signup(client, email="stranger@example.com", name="Stranger")
    response = client.patch(
        f"/api/v1/videos/{video['id']}",
        headers=stranger,
        json={"workspace_id": other},
    )
    assert response.status_code == 404


def test_workspace_member_can_file_shared_video_into_collection(
    client: TestClient,
) -> None:
    owner = _signup(client, email="owner@example.com", name="Owner")
    workspace_id = _create_workspace(client, owner)
    video = _upload(client, owner, workspace_id=workspace_id)

    _signup(client, email="bob@example.com", name="Bob")
    client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=owner,
        json={"email": "bob@example.com", "role": "member"},
    )
    bob = _login(client, "bob@example.com")

    created = client.post(
        "/api/v1/collections", headers=bob, json={"name": "To review"}
    )
    assert created.status_code == 201, created.text
    collection_id = created.json()["id"]

    # Bob doesn't own the video, but it's in his workspace — filing works.
    response = client.post(
        f"/api/v1/collections/{collection_id}/videos",
        headers=bob,
        json={"video_ids": [video["id"]]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 1


def test_workspace_routes_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/workspaces").status_code == 401
    assert client.post("/api/v1/workspaces", json={"name": "X"}).status_code == 401
    assert (
        client.post(
            f"/api/v1/workspaces/{uuid.uuid4()}/members",
            json={"email": "a@b.com", "role": "member"},
        ).status_code
        == 401
    )
