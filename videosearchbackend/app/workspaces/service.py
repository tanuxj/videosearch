"""Workspace business logic: CRUD, membership and role management.

Kept free of FastAPI types, matching the video and collection services:
these functions raise domain errors and the route layer decides the HTTP
status.

Role model (strongest → weakest): owner > admin > member > viewer.

* **owner** — created with the workspace; may do everything including
  deleting it. There is exactly one, and it can never be reassigned or
  removed (a workspace can't be left ownerless).
* **admin** — manages members (invite, change roles, remove) and the
  workspace itself (rename); may also do everything members can.
* **member** — uploads, moves and deletes videos in the workspace.
* **viewer** — read-only: watches, searches, shares. No mutations.

Videos are not the workspace's concern directly — `app/videos/service.py`
calls `is_member`/`member_role` to decide whether a caller may see or
mutate a video that carries a `workspace_id`.
"""

import logging
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.service import normalize_email
from app.workspaces.models import Workspace, WorkspaceMember

logger = logging.getLogger(__name__)

# Roles that may manage the workspace itself and its members.
_MANAGER_ROLES = ("owner", "admin")
# Roles that may mutate the workspace's videos (upload/move/delete).
_EDITOR_ROLES = ("owner", "admin", "member")


class WorkspaceError(Exception):
    """Base class for workspace failures."""


class WorkspaceNotFound(WorkspaceError):
    """No such workspace, or the caller isn't a member (same 404)."""


class Forbidden(WorkspaceError):
    """The caller is a member but their role isn't high enough."""


class MemberNotFound(WorkspaceError):
    """No such membership row (or it belongs to a different workspace)."""


class AlreadyMember(WorkspaceError):
    """The invited account is already in the workspace."""


class UserNotFound(WorkspaceError):
    """No account exists with the invited email."""


class OwnerCannotLeave(WorkspaceError):
    """The owner must delete the workspace, not leave it."""


class CannotModifyOwner(WorkspaceError):
    """The owner's role can't be changed or the owner can't be removed."""


async def _member_row(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMember | None:
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def is_member(db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """True when `user_id` belongs to the workspace at all (any role)."""
    return await _member_row(db, workspace_id, user_id) is not None


async def member_role(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> str | None:
    """The caller's role in the workspace, or None when not a member."""
    row = await _member_row(db, workspace_id, user_id)
    return row.role if row else None


async def accessible_workspace_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Every workspace the user belongs to — what `list_videos` scopes by."""
    result = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
    )
    return {row[0] for row in result.all()}


async def _require_manager(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> Workspace:
    """Fetch a workspace, requiring the caller to be owner or admin."""
    workspace = await db.get(Workspace, workspace_id)
    role = await member_role(db, workspace_id, user_id)
    if workspace is None or role is None:
        raise WorkspaceNotFound(workspace_id)
    if role not in _MANAGER_ROLES:
        raise Forbidden(workspace_id)
    return workspace


async def list_workspaces(
    db: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Workspace, str, int]]:
    """The user's workspaces as (workspace, my_role, member_count).

    One query for the whole list: membership rows are joined to workspaces
    and counted in the same statement, so the teams page doesn't fire N+1
    count queries. Ordered by name so the switcher is stable.
    """
    result = await db.execute(
        select(
            Workspace,
            WorkspaceMember.role,
            func.count(WorkspaceMember.user_id),
        )
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user_id)
        .group_by(Workspace.id, WorkspaceMember.role)
        .order_by(func.lower(Workspace.name).asc())
    )
    return [(row[0], row[1], row[2]) for row in result.all()]


async def create_workspace(
    db: AsyncSession, *, user_id: uuid.UUID, name: str
) -> Workspace:
    """Create a workspace with the caller as its sole owner member."""
    workspace = Workspace(name=name.strip(), created_by=user_id)
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user_id,
            role="owner",
        )
    )
    await db.commit()
    await db.refresh(workspace)
    logger.info("Workspace created: %s (%r) by %s", workspace.id, workspace.name, user_id)
    return workspace


async def rename_workspace(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID, *, name: str
) -> Workspace:
    workspace = await _require_manager(db, user_id, workspace_id)
    workspace.name = name.strip()
    await db.commit()
    await db.refresh(workspace)
    logger.info("Workspace renamed: %s (%r)", workspace_id, workspace.name)
    return workspace


async def delete_workspace(db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    """Delete a workspace (owner only).

    Videos with this `workspace_id` revert to their uploaders' personal
    libraries — the FK is ON DELETE SET NULL — so deleting a team never
    deletes its footage.
    """
    workspace = await _require_manager(db, user_id, workspace_id)
    role = await member_role(db, workspace_id, user_id)
    if role != "owner":
        raise Forbidden(workspace_id)
    await db.delete(workspace)
    await db.commit()
    logger.info("Workspace deleted: %s by %s", workspace_id, user_id)


async def list_members(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> list[tuple[WorkspaceMember, User]]:
    """Every member with their account info, oldest join first.

    Any member may see the roster (it's how the teams page renders) — only
    *changes* are gated to owner/admin.
    """
    workspace = await db.get(Workspace, workspace_id)
    role = await member_role(db, workspace_id, user_id)
    if workspace is None or role is None:
        raise WorkspaceNotFound(workspace_id)
    result = await db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at.asc())
    )
    return [(row[0], row[1]) for row in result.all()]


async def invite_member(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    email: str,
    role: str,
) -> WorkspaceMember:
    """Add an existing account to the workspace (owner/admin only).

    The invited account must already exist — there is no email pipeline, so
    a nonexistent address can't be confirmed. An invite is idempotent for
    the *same* role (ON CONFLICT DO NOTHING), but raising the role of an
    existing member through an invite is rejected rather than silently
    applied — use the role endpoint for that.
    """
    await _require_manager(db, user_id, workspace_id)
    target = await db.execute(select(User).where(User.email == normalize_email(email)))
    target_user = target.scalar_one_or_none()
    if target_user is None:
        raise UserNotFound(email)

    existing = await _member_row(db, workspace_id, target_user.id)
    if existing is not None:
        if existing.role == role:
            return existing
        raise AlreadyMember(email)

    member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=target_user.id,
        role=role,
    )
    db.add(member)
    try:
        await db.commit()
    except IntegrityError as exc:
        # A concurrent invite won the race — treat it as already a member.
        await db.rollback()
        raise AlreadyMember(email) from exc
    await db.refresh(member)
    logger.info(
        "Invited %s to workspace %s as %s", email, workspace_id, role
    )
    return member


async def set_member_role(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    target_user_id: uuid.UUID,
    *,
    role: str,
) -> WorkspaceMember:
    """Change a member's role (owner/admin only; never the owner's)."""
    await _require_manager(db, user_id, workspace_id)
    target = await _member_row(db, workspace_id, target_user_id)
    if target is None:
        raise MemberNotFound(target_user_id)
    if target.role == "owner":
        raise CannotModifyOwner(target_user_id)
    target.role = role
    await db.commit()
    await db.refresh(target)
    logger.info(
        "Role for %s in workspace %s changed to %s", target_user_id, workspace_id, role
    )
    return target


async def remove_member(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    target_user_id: uuid.UUID,
) -> None:
    """Remove a member (owner/admin only; never the owner)."""
    await _require_manager(db, user_id, workspace_id)
    target = await _member_row(db, workspace_id, target_user_id)
    if target is None:
        raise MemberNotFound(target_user_id)
    if target.role == "owner":
        raise CannotModifyOwner(target_user_id)
    await db.delete(target)
    await db.commit()
    logger.info("Member %s removed from workspace %s", target_user_id, workspace_id)


async def leave_workspace(db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    """The caller leaves the workspace. The owner can't — they must delete it.

    Videos the leaver uploaded stay in the workspace (they're the team's
    footage now); their membership is what's revoked, not their uploads.
    """
    role = await member_role(db, workspace_id, user_id)
    if role is None:
        raise WorkspaceNotFound(workspace_id)
    if role == "owner":
        raise OwnerCannotLeave(workspace_id)
    await db.execute(
        delete(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    await db.commit()
    logger.info("User %s left workspace %s", user_id, workspace_id)


# ── Helpers for the video service ────────────────────────────


def can_edit_videos(role: str | None) -> bool:
    """Whether a role may upload/move/delete videos in the workspace."""
    return role in _EDITOR_ROLES
