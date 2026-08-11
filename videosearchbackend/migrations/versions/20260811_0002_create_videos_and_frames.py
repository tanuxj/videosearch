"""create videos and frames

Revision ID: 20260811_0002
Revises: 20260811_0001
Create Date: 2026-08-11

Video index schema:

* ``videos`` — one row per uploaded video, owned by a user. `status` walks
  ``processing → ready`` (or ``failed`` with an `error` message). `storage_key`
  is the object key inside the R2 bucket; ``frames_total`` / ``frames_indexed``
  back the frontend's progress bar.
* ``frames`` — one row per indexed frame: the CLIP image embedding
  (512 dims for clip-ViT-B-32) plus the second it came from. A unique
  ``(video_id, timestamp_sec)`` pair keeps 1-fps extraction honest, and the
  HNSW cosine index is what makes ``ORDER BY embedding <=> $vec`` fast.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260811_0002"
down_revision: str | None = "20260811_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The compose image preloads `vector`; this keeps a bare Postgres working too.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE videos (
            id               UUID             NOT NULL DEFAULT gen_random_uuid(),
            owner_id         UUID             NOT NULL,
            name             VARCHAR(255)     NOT NULL,
            size_bytes       BIGINT           NOT NULL,
            duration_seconds DOUBLE PRECISION,
            status           VARCHAR(16)      NOT NULL DEFAULT 'processing',
            error            TEXT,
            storage_key      VARCHAR(512)     NOT NULL,
            poster_key       VARCHAR(512),
            frames_total     INTEGER          NOT NULL DEFAULT 0,
            frames_indexed   INTEGER          NOT NULL DEFAULT 0,
            created_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ      NOT NULL DEFAULT now(),
            CONSTRAINT pk_videos PRIMARY KEY (id),
            CONSTRAINT fk_videos_owner_id_users
                FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT ck_videos_status
                CHECK (status IN ('processing', 'ready', 'failed'))
        )
    """)

    # Supports "list my videos" and cascade cleanup per user.
    op.execute("CREATE INDEX ix_videos_owner_id ON videos (owner_id)")

    op.execute("""
        CREATE TABLE frames (
            id            UUID             NOT NULL DEFAULT gen_random_uuid(),
            video_id      UUID             NOT NULL,
            timestamp_sec DOUBLE PRECISION NOT NULL,
            embedding     VECTOR(512)      NOT NULL,
            thumb_key     VARCHAR(512),
            created_at    TIMESTAMPTZ      NOT NULL DEFAULT now(),
            CONSTRAINT pk_frames PRIMARY KEY (id),
            CONSTRAINT fk_frames_video_id_videos
                FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE
        )
    """)

    # Supports "fetch all frames for a video" during indexing.
    op.execute("CREATE INDEX ix_frames_video_id ON frames (video_id)")

    # One frame per second, per video — duplicate extraction is a bug.
    op.execute("""
        ALTER TABLE frames
            ADD CONSTRAINT uq_frames_video_id_timestamp_sec
            UNIQUE (video_id, timestamp_sec)
    """)

    # Cosine-distance HNSW index — the search accelerator.
    op.execute("""
        CREATE INDEX ix_frames_embedding_hnsw
            ON frames USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade() -> None:
    # Dropping the tables takes their indexes and foreign keys with them.
    op.execute("DROP TABLE frames")
    op.execute("DROP TABLE videos")
