"""add notifications

Revision ID: 20260816_0012
Revises: 20260816_0011
Create Date: 2026-08-16

In-app notifications: one row per event the user should see in the UI.
Today the indexing pipeline writes exactly one kind — ``indexed``, when a
video settles on ``status == 'ready'`` — and the frontend's bell reads the
list. Notifications are strictly per-user, addressed to the video's
uploader, and cascade with both the account and the video.

The unique (user_id, video_id, kind) index makes the pipeline's write
idempotent (re-runs can't double-ring the bell) and its leftmost prefix
serves list-by-user lookups. The video_id index keeps the FK cascade cheap.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260816_0012"
down_revision: str | None = "20260816_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE notifications ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
        "video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE, "
        "kind VARCHAR(16) NOT NULL DEFAULT 'indexed', "
        "read BOOLEAN NOT NULL DEFAULT false, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_notifications_user_video_kind "
        "ON notifications (user_id, video_id, kind)"
    )
    op.execute("CREATE INDEX ix_notifications_video_id ON notifications (video_id)")


def downgrade() -> None:
    op.execute("DROP TABLE notifications")
