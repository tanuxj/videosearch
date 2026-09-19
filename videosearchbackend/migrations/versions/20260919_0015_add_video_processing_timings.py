"""Add videos.processing_started_at / processing_completed_at.

How long a video took to index, so the UI can tell the user "processed in
2m 14s" instead of leaving them to guess. Two timestamps rather than one
elapsed number: the pair also gives a live "running for 40s" reading while
the video is still `processing`, which a stored duration cannot.

Both nullable and backfilled to NULL — rows that predate this migration
were indexed before anything was measured, and inventing a duration for
them from `created_at`/`updated_at` would be a guess (`updated_at` moves on
every later edit, so it is not when indexing finished).

Revision ID: 20260919_0015
Revises: 20260917_0014
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0015"
down_revision: str | None = "20260917_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "videos",
        sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("videos", "processing_completed_at")
    op.drop_column("videos", "processing_started_at")
