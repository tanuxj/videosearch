"""Add videos.expires_at for homepage-trial uploads.

Trial sessions (the public homepage's try-it demo) get a deletion deadline
stamped on every video they create; the purge sweep deletes expired rows and
their stored files. Null for every other video — registered uploads are
permanent until their owner deletes them.

Revision ID: 20260917_0013
Revises: 20260816_0012
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa

revision: str = "20260917_0013"
down_revision: str | None = "20260816_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable, unindexed by default: only trial uploads carry a deadline,
    # and the sweep's WHERE clause (expires_at <= now, not null) reads a
    # sliver of the table. An index is added for when trial traffic makes
    # expired-row lookups hot — a partial index keeps it tiny.
    op.add_column("videos", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_videos_expires_at_active",
        "videos",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_videos_expires_at_active", table_name="videos")
    op.drop_column("videos", "expires_at")
