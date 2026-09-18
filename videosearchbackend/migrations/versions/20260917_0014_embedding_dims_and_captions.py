"""Resize frames.embedding for the configured model + add caption columns.

Two schema changes in one migration because they belong to one switch:

1. `frames.embedding` is resized to the dimension of the configured
   `embedding_model` (EMBEDDING_DIMS in app.core.config: 512 for CLIP,
   768 for SigLIP 2). Changing the model changes the embedding space
   entirely — a vector from the old tower is meaningless next to one from
   the new — so this migration **deletes every frame row** rather than
   leave a column of vectors that would silently rank nonsense after the
   switch. Frames are derived data: timestamps, vectors and thumbnail keys
   rebuilt by re-indexing, while videos, transcripts and saved clips keep
   their rows (thumbnail objects stay in storage and are re-attached on
   re-index). Downgrading restores the column width but not the deleted
   rows, for the same reason.

2. `frames.caption` / `frames.caption_embedding` — Florence-2's dense
   caption of the frame and its text-tower embedding, both nullable
   because captioning is opt-in at index time and old frames predate it.
   The caption HNSW index uses cosine ops like the main one; it is
   partial (caption_embedding IS NOT NULL) so it stays tiny until
   captions actually exist.

Revision ID: 20260917_0014
Revises: 20260917_0013
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.core.config import EMBEDDING_DIMS, get_settings

revision: str = "20260917_0014"
down_revision: str | None = "20260917_0013"
branch_labels = None
depends_on = None


def _resize_embedding(dims: int) -> None:
    """Point frames.embedding at `dims` dimensions, discarding its rows.

    pgvector registers no cast between different vector widths, so the ALTER
    must run on an empty column — DELETE first, then retype (USING NULL keeps
    PostgreSQL from hunting for a cast that does not exist), then recreate the
    HNSW index over the now-empty column.
    """
    op.drop_index("ix_frames_embedding_hnsw", table_name="frames")
    op.execute("DELETE FROM frames")
    op.execute(
        f"ALTER TABLE frames ALTER COLUMN embedding TYPE vector({dims}) USING NULL::vector"
    )
    op.create_index(
        "ix_frames_embedding_hnsw",
        "frames",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def upgrade() -> None:
    dims = EMBEDDING_DIMS[get_settings().embedding_model]
    _resize_embedding(dims)

    op.add_column("frames", sa.Column("caption", sa.Text(), nullable=True))
    op.add_column(
        "frames",
        sa.Column("caption_embedding", Vector(dims), nullable=True),
    )
    # Partial: frames without captions (everything before this migration,
    # or captioning disabled) contribute nothing to the index.
    op.create_index(
        "ix_frames_caption_embedding_hnsw",
        "frames",
        ["caption_embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"caption_embedding": "vector_cosine_ops"},
        postgresql_where=sa.text("caption_embedding IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_frames_caption_embedding_hnsw", table_name="frames")
    op.drop_column("frames", "caption_embedding")
    op.drop_column("frames", "caption")
    _resize_embedding(EMBEDDING_DIMS["clip"])
