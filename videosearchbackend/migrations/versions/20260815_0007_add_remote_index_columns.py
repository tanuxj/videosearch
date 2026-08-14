"""add Twelve Labs remote index columns to videos

Revision ID: 20260815_0007
Revises: 20260814_0006
Create Date: 2026-08-15

Adds the bookkeeping for the Twelve Labs (Marengo) index, which runs *beside*
the local CLIP index rather than replacing it:

* ``remote_index_status`` — its own lifecycle, independent of ``status``, for
  the same reason ``transcript_status`` is: the work happens on someone else's
  GPUs on its own schedule.
* ``remote_asset_id`` / ``remote_indexed_asset_id`` — their ids for the
  uploaded file and for that file's membership of an index.
* ``remote_video_id`` — search results are keyed by this, so it is what maps a
  hit back to a row here. Indexed for exactly that lookup.

Existing rows backfill to ``'pending'`` rather than ``'skipped'``: unlike the
transcription migration, these videos *can* still be indexed remotely (the
file is in storage and the API pulls it by URL), so leaving them eligible is
correct. Nothing runs automatically for them — the backfill endpoint does.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260815_0007"
down_revision: str | None = "20260814_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE videos
            ADD COLUMN remote_index_status VARCHAR(16) NOT NULL DEFAULT 'pending'
    """)
    op.execute("ALTER TABLE videos ADD COLUMN remote_index_error TEXT")
    op.execute("ALTER TABLE videos ADD COLUMN remote_asset_id VARCHAR(64)")
    op.execute("ALTER TABLE videos ADD COLUMN remote_indexed_asset_id VARCHAR(64)")
    op.execute("ALTER TABLE videos ADD COLUMN remote_video_id VARCHAR(64)")
    op.execute("""
        ALTER TABLE videos
            ADD CONSTRAINT ck_videos_remote_index_status
            CHECK (remote_index_status IN
                ('pending', 'processing', 'ready', 'failed', 'skipped'))
    """)
    # Search hits arrive keyed by the provider's video id; this is the lookup
    # that turns one back into a row.
    op.execute("CREATE INDEX ix_videos_remote_video_id ON videos (remote_video_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_videos_remote_video_id")
    op.execute("ALTER TABLE videos DROP CONSTRAINT IF EXISTS ck_videos_remote_index_status")
    op.execute("ALTER TABLE videos DROP COLUMN remote_video_id")
    op.execute("ALTER TABLE videos DROP COLUMN remote_indexed_asset_id")
    op.execute("ALTER TABLE videos DROP COLUMN remote_asset_id")
    op.execute("ALTER TABLE videos DROP COLUMN remote_index_error")
    op.execute("ALTER TABLE videos DROP COLUMN remote_index_status")
