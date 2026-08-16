"""Request and response models for the workspace routes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.workspaces.models import WORKSPACE_NAME_MAX_LENGTH

# Roles a caller may *assign* to someone else. `owner` is deliberately not
# here: a workspace always has exactly one owner (the creator), and creating
# a second one via an invite would be a bug.
ASSIGNABLE_ROLES = ("admin", "member", "viewer")


class WorkspaceOut(BaseModel):
    """Public view of a workspace — the member's own role included."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    # The caller's role in this workspace — what the UI renders its
    # permissions from. Populated by the route layer after `model_validate`
    # (it lives on the membership row, not the workspace), so it defaults
    # here and is filled in via `model_copy(update=...)`.
    role: str = "member"
    # How many accounts are members (including the caller).
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class WorkspaceListOut(BaseModel):
    items: list[WorkspaceOut]
    count: int = Field(description="Number of workspaces returned.")


class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=WORKSPACE_NAME_MAX_LENGTH, examples=["Design"])


class WorkspaceRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=WORKSPACE_NAME_MAX_LENGTH, examples=["Design"])


class WorkspaceMemberOut(BaseModel):
    """One member of a workspace, with their account info and role."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    name: str
    email: EmailStr
    role: str
    created_at: datetime


class WorkspaceDetailOut(BaseModel):
    """A workspace plus its full member list — the teams page's payload."""

    workspace: WorkspaceOut
    members: list[WorkspaceMemberOut]


class MemberInviteIn(BaseModel):
    """Invite an existing account by email with a starting role.

    Only accounts that already exist can join — there is no email-sending
    pipeline in this app, so inviting a stranger would be a dead end.
    """

    email: EmailStr = Field(examples=["alex@company.com"])
    role: str = Field(default="member", pattern="^(admin|member|viewer)$")


class MemberRoleIn(BaseModel):
    role: str = Field(pattern="^(admin|member|viewer)$")
