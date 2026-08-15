"""add video has_video

Revision ID: 20260815_0009
Revises: 20260815_0008
Create Date: 2026-08-15

`videos.has_video` records whether the file carries a video track. The indexing
pipeline sets it at probe time: True for normal videos, False for audio-only
recordings (a mic-only save from the Record tab has nothing to frame-index).
The frontend uses it to keep audio-only recordings out of the scene-search
picker — they can't be searched by frame, so they belong in the library, not
the search box.

Nullable on purpose: rows are created before the pipeline probes the file, and
pre-existing rows have no signal at all. The frontend treats null as "has
video" so old uploads stay searchable.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260815_0009"
down_revision: str | None = "20260815_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE videos ADD COLUMN has_video BOOLEAN")


def downgrade() -> None:
    op.execute("ALTER TABLE videos DROP COLUMN has_video")
