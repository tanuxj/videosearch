"""add video source

Revision ID: 20260815_0008
Revises: 20260815_0007
Create Date: 2026-08-15

`videos.source` records how a video entered the library — `upload` (default),
`recording` (saved from the Record tab) or `url` (imported from a link). The
frontend tags recordings with it so they read differently from plain uploads
in the library. Existing rows default to `upload`, which is the truth for
everything indexed before this column existed.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260815_0008"
down_revision: str | None = "20260815_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Name must match what the model's naming convention produces
    # (`ck_videos_source`) so Alembic autogenerate stays in sync.
    op.execute("ALTER TABLE videos ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT 'upload'")
    op.execute(
        "ALTER TABLE videos ADD CONSTRAINT ck_videos_source "
        "CHECK (source IN ('upload', 'recording', 'url'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE videos DROP CONSTRAINT ck_videos_source")
    op.execute("ALTER TABLE videos DROP COLUMN source")
