"""Workspaces: teams that share a video library.

* ``workspaces`` — one row per team. The creator starts as its only member
  with role ``owner``.
* ``workspace_members`` — who belongs, and what they may do. Roles are
  ``owner`` (everything, including deleting the workspace), ``admin``
  (manage members and the workspace itself), ``member`` (upload/move/delete
  videos), and ``viewer`` (read-only: watch, search, share).

Membership is what grants access to the workspace's videos. A video carries a
nullable ``workspace_id`` (see ``app/videos/models.py``): null means it lives
in its uploader's personal library, otherwise every member of the workspace
can see it. Deleting a workspace sets ``workspace_id`` back to null, so the
footage reverts to each uploader's personal library rather than vanishing.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# Longest workspace name. Mirrored by the API schema's `max_length`.
WORKSPACE_NAME_MAX_LENGTH = 120

# What a member may do, strongest to weakest. The API rejects invites and
# role changes that would create a second owner — a workspace always has
# exactly one.
WORKSPACE_ROLES = ("owner", "admin", "member", "viewer")


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(WORKSPACE_NAME_MAX_LENGTH), nullable=False)
    # The account that created the workspace — kept for display and as the
    # source of truth for who the original `owner` role belongs to.
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Workspace {self.name!r}>"


class WorkspaceMember(Base):
    """One user's membership in one workspace, with their role.

    The composite primary key makes re-adding a member a no-op at the
    database level and gives the ``(workspace_id, user_id)`` pair a unique
    index for free.
    """

    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # One of WORKSPACE_ROLES.
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="member", server_default=text("'member'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="members")

    __table_args__ = (
        CheckConstraint(f"role IN {tuple(WORKSPACE_ROLES)}", name="role"),
        Index("ix_workspace_members_user_id", "user_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (  # noqa: E501 - debugging aid, not user-facing
            f"<WorkspaceMember workspace={self.workspace_id} "
            f"user={self.user_id} role={self.role}>"
        )
