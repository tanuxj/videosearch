"""add workspaces and workspace members

Revision ID: 20260816_0011
Revises: 20260815_0010
Create Date: 2026-08-16

Workspaces give a video-search SaaS its first multi-user primitive: a team
of accounts sharing one library. `workspaces` holds the team itself,
`workspace_members` who belongs and what they may do (owner/admin/member/
viewer), and `videos.workspace_id` moves a video from its uploader's
personal library into the shared one. The column is nullable on purpose:
every existing video stays personal (null) and the frontend treats null as
"my library", so this migration is a strict addition.

Deleting a workspace sets `workspace_id` back to null (ON DELETE SET NULL)
rather than deleting the footage — the videos revert to their uploaders'
personal libraries. Member rows cascade with the workspace; the owner row
is created with the workspace, so it can never be left ownerless.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260816_0011"
down_revision: str | None = "20260815_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE workspaces ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "name VARCHAR(120) NOT NULL, "
        "created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    op.execute("CREATE INDEX ix_workspaces_created_by ON workspaces (created_by)")
    op.execute(
        "CREATE TABLE workspace_members ("
        "workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "role VARCHAR(16) NOT NULL DEFAULT 'member', "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "PRIMARY KEY (workspace_id, user_id))"
    )
    op.execute("CREATE INDEX ix_workspace_members_user_id ON workspace_members (user_id)")
    op.execute(
        "ALTER TABLE workspace_members ADD CONSTRAINT ck_workspace_members_role "
        "CHECK (role IN ('owner', 'admin', 'member', 'viewer'))"
    )
    op.execute(
        "ALTER TABLE videos ADD COLUMN workspace_id UUID "
        "REFERENCES workspaces(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX ix_videos_workspace_id ON videos (workspace_id)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_videos_workspace_id")
    op.execute("ALTER TABLE videos DROP COLUMN workspace_id")
    op.execute("DROP TABLE workspace_members")
    op.execute("DROP TABLE workspaces")
