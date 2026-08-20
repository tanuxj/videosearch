"""Workspace routes: create, manage members, and leave.

The teams page's entire backend. Membership and role changes are gated to
owner/admin by the service; the route layer maps domain errors to HTTP
statuses (404 for anything unseeable, 403 for role too low, 409 for
conflicts like re-inviting a member or leaving as owner).
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import CurrentUser, DbSession
from app.auth.schemas import MessageResponse
from app.workspaces import service as workspaces_service
from app.workspaces.models import Workspace
from app.workspaces.schemas import (
    MemberInviteIn,
    MemberRoleIn,
    WorkspaceCreateIn,
    WorkspaceDetailOut,
    WorkspaceListOut,
    WorkspaceMemberOut,
    WorkspaceOut,
    WorkspaceRenameIn,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _error(exc: workspaces_service.WorkspaceError, fallback: str) -> HTTPException:
    """Map a domain error to the status its name implies."""
    if isinstance(exc, workspaces_service.WorkspaceNotFound):
        return HTTPException(status_code=404, detail="Workspace not found")
    if isinstance(exc, workspaces_service.Forbidden):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role in this workspace doesn't allow that.",
        )
    if isinstance(exc, workspaces_service.MemberNotFound):
        return HTTPException(status_code=404, detail="Member not found")
    if isinstance(exc, workspaces_service.UserNotFound):
        return HTTPException(
            status_code=404,
            detail="No account exists with that email — they need to sign up first.",
        )
    if isinstance(exc, workspaces_service.AlreadyMember):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That account is already a member of this workspace.",
        )
    if isinstance(exc, workspaces_service.OwnerCannotLeave):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The owner can't leave — delete the workspace instead.",
        )
    if isinstance(exc, workspaces_service.CannotModifyOwner):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The workspace owner's role can't be changed or removed.",
        )
    return HTTPException(status_code=500, detail=fallback)


@router.get(
    "",
    response_model=WorkspaceListOut,
    summary="List my workspaces",
    description="Every workspace the signed-in user belongs to, with their role and member count.",
)
async def list_workspaces(user: CurrentUser, db: DbSession) -> WorkspaceListOut:
    rows = await workspaces_service.list_workspaces(db, user.id)
    items = [
        WorkspaceOut.model_validate(workspace).model_copy(
            update={"role": role, "member_count": count}
        )
        for workspace, role, count in rows
    ]
    return WorkspaceListOut(items=items, count=len(items))


@router.post(
    "",
    response_model=WorkspaceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a workspace",
    description="Opens a new workspace with the caller as its owner member.",
)
async def create_workspace(
    user: CurrentUser, db: DbSession, payload: WorkspaceCreateIn
) -> WorkspaceOut:
    workspace = await workspaces_service.create_workspace(db, user_id=user.id, name=payload.name)
    return WorkspaceOut.model_validate(workspace).model_copy(
        update={"role": "owner", "member_count": 1}
    )


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceDetailOut,
    summary="Workspace detail with its members",
    description="The workspace plus its full member roster. Any member may view it.",
    responses={404: {"description": "Workspace not found"}},
)
async def get_workspace(
    user: CurrentUser, db: DbSession, workspace_id: uuid.UUID
) -> WorkspaceDetailOut:
    try:
        members = await workspaces_service.list_members(db, user.id, workspace_id)
    except workspaces_service.WorkspaceError as exc:
        raise _error(exc, "Could not load the workspace") from exc

    workspace = await db.get(Workspace, workspace_id)
    role = await workspaces_service.member_role(db, workspace_id, user.id)
    return WorkspaceDetailOut(
        workspace=WorkspaceOut.model_validate(workspace).model_copy(
            update={"role": role, "member_count": len(members)}
        ),
        members=[
            WorkspaceMemberOut(
                user_id=member.user_id,
                name=account.name,
                email=account.email,
                role=member.role,
                created_at=member.created_at,
            )
            for member, account in members
        ],
    )


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceOut,
    summary="Rename a workspace",
    description="Owner or admin may rename the workspace.",
    responses={
        403: {"description": "Role too low"},
        404: {"description": "Workspace not found"},
    },
)
async def rename_workspace(
    user: CurrentUser,
    db: DbSession,
    workspace_id: uuid.UUID,
    payload: WorkspaceRenameIn,
) -> WorkspaceOut:
    try:
        workspace = await workspaces_service.rename_workspace(
            db, user.id, workspace_id, name=payload.name
        )
    except workspaces_service.WorkspaceError as exc:
        raise _error(exc, "Could not rename the workspace") from exc
    role = await workspaces_service.member_role(db, workspace_id, user.id)
    count = len(await workspaces_service.list_members(db, user.id, workspace_id))
    return WorkspaceOut.model_validate(workspace).model_copy(
        update={"role": role, "member_count": count}
    )


@router.delete(
    "/{workspace_id}",
    response_model=MessageResponse,
    summary="Delete a workspace",
    description=(
        "Owner only. The workspace's videos revert to their uploaders' "
        "personal libraries — nothing is deleted."
    ),
    responses={
        403: {"description": "Only the owner can delete"},
        404: {"description": "Workspace not found"},
    },
)
async def delete_workspace(
    user: CurrentUser, db: DbSession, workspace_id: uuid.UUID
) -> MessageResponse:
    try:
        await workspaces_service.delete_workspace(db, user.id, workspace_id)
    except workspaces_service.WorkspaceError as exc:
        raise _error(exc, "Could not delete the workspace") from exc
    return MessageResponse(detail="Workspace deleted")


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a member by email",
    description=(
        "Adds an existing account to the workspace (owner/admin only). The "
        "account must already have signed up — there's no invite email."
    ),
    responses={
        403: {"description": "Role too low"},
        404: {"description": "Workspace or account not found"},
        409: {"description": "Already a member"},
    },
)
async def invite_member(
    user: CurrentUser,
    db: DbSession,
    workspace_id: uuid.UUID,
    payload: MemberInviteIn,
) -> WorkspaceMemberOut:
    try:
        member = await workspaces_service.invite_member(
            db,
            user.id,
            workspace_id,
            email=payload.email,
            role=payload.role,
        )
    except workspaces_service.WorkspaceError as exc:
        raise _error(exc, "Could not invite that member") from exc

    from app.auth.service import get_user_by_id

    account = await get_user_by_id(db, member.user_id)
    return WorkspaceMemberOut(
        user_id=member.user_id,
        name=account.name if account else "Member",
        email=account.email if account else payload.email,
        role=member.role,
        created_at=member.created_at,
    )


@router.patch(
    "/{workspace_id}/members/{member_id}",
    response_model=WorkspaceMemberOut,
    summary="Change a member's role",
    description=(
        "Owner or admin may change any non-owner member's role. The owner's role is immutable."
    ),
    responses={
        403: {"description": "Role too low"},
        404: {"description": "Workspace or member not found"},
        409: {"description": "Cannot change the owner"},
    },
)
async def set_member_role(
    user: CurrentUser,
    db: DbSession,
    workspace_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: MemberRoleIn,
) -> WorkspaceMemberOut:
    try:
        member = await workspaces_service.set_member_role(
            db, user.id, workspace_id, member_id, role=payload.role
        )
    except workspaces_service.WorkspaceError as exc:
        raise _error(exc, "Could not change that member's role") from exc

    from app.auth.service import get_user_by_id

    account = await get_user_by_id(db, member.user_id)
    return WorkspaceMemberOut(
        user_id=member.user_id,
        name=account.name if account else "Member",
        email=account.email if account else "",
        role=member.role,
        created_at=member.created_at,
    )


@router.delete(
    "/{workspace_id}/members/{member_id}",
    response_model=MessageResponse,
    summary="Remove a member",
    description="Owner or admin may remove any non-owner member.",
    responses={
        403: {"description": "Role too low"},
        404: {"description": "Workspace or member not found"},
        409: {"description": "Cannot remove the owner"},
    },
)
async def remove_member(
    user: CurrentUser,
    db: DbSession,
    workspace_id: uuid.UUID,
    member_id: uuid.UUID,
) -> MessageResponse:
    try:
        await workspaces_service.remove_member(db, user.id, workspace_id, member_id)
    except workspaces_service.WorkspaceError as exc:
        raise _error(exc, "Could not remove that member") from exc
    return MessageResponse(detail="Member removed")


@router.post(
    "/{workspace_id}/leave",
    response_model=MessageResponse,
    summary="Leave a workspace",
    description="The caller leaves the workspace. The owner must delete it instead.",
    responses={
        404: {"description": "Workspace not found"},
        409: {"description": "The owner can't leave"},
    },
)
async def leave_workspace(
    user: CurrentUser, db: DbSession, workspace_id: uuid.UUID
) -> MessageResponse:
    try:
        await workspaces_service.leave_workspace(db, user.id, workspace_id)
    except workspaces_service.WorkspaceError as exc:
        raise _error(exc, "Could not leave the workspace") from exc
    return MessageResponse(detail="Left workspace")
