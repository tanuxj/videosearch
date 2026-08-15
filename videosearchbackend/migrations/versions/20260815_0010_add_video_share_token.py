"""add video share_token

Revision ID: 20260815_0010
Revises: 20260815_0009
Create Date: 2026-08-15

`videos.share_token` is the unguessable key in a `/share/<token>` link — the
public share page looks videos up by it, so a recipient with the link can
watch the video and read its transcript without an account. Null until the
owner shares the video the first time (the link is minted lazily); clearing
the token (the unshare route) revokes every outstanding link at once.

The unique index is what makes the token a lookup key rather than a filter,
and matches what the model's `unique=True, index=True` would produce
(`ix_videos_share_token`), so Alembic autogenerate stays in sync.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260815_0010"
down_revision: str | None = "20260815_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE videos ADD COLUMN share_token VARCHAR(64)")
    op.execute("CREATE UNIQUE INDEX ix_videos_share_token ON videos (share_token)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_videos_share_token")
    op.execute("ALTER TABLE videos DROP COLUMN share_token")
