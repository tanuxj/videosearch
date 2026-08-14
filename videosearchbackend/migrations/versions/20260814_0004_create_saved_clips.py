"""create saved_clips

Revision ID: 20260814_0004
Revises: 20260814_0003
Create Date: 2026-08-14

Saved-clips schema:

* ``saved_clips`` — one row per scene kept from an import. Created when a URL
  import carries a prompt: after indexing, the import job runs the CLIP
  search and persists the best scenes (``start``/``end``/``frame``/``score``)
  so the library can show them without a manual search. ``end`` is quoted —
  it is a reserved word in PostgreSQL. Deleting a video cascades to its
  clips.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_0004"
down_revision: str | None = "20260814_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE saved_clips (
            id         UUID             NOT NULL DEFAULT gen_random_uuid(),
            owner_id   UUID             NOT NULL,
            video_id   UUID             NOT NULL,
            prompt     VARCHAR(300)     NOT NULL,
            start      DOUBLE PRECISION NOT NULL,
            "end"      DOUBLE PRECISION NOT NULL,
            frame      DOUBLE PRECISION NOT NULL,
            score      DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMPTZ      NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ      NOT NULL DEFAULT now(),
            CONSTRAINT pk_saved_clips PRIMARY KEY (id),
            CONSTRAINT fk_saved_clips_owner_id_users
                FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT fk_saved_clips_video_id_videos
                FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE
        )
    """)

    # Supports "list clips on my video" and cascade cleanup per user / video.
    op.execute("CREATE INDEX ix_saved_clips_owner_id ON saved_clips (owner_id)")
    op.execute("CREATE INDEX ix_saved_clips_video_id ON saved_clips (video_id)")


def downgrade() -> None:
    op.execute("DROP TABLE saved_clips")
