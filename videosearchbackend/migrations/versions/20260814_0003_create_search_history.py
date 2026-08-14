"""create search_history

Revision ID: 20260814_0003
Revises: 20260811_0002
Create Date: 2026-08-14

Search history schema:

* ``search_history`` — one row per search the user ran: the prompt, the video
  it was run against, and a JSONB snapshot of the clips that came back
  (``[{id, start, end, frame, score}, …]``). Deleting a video cascades to its
  history, since a record with no video left is unplayable.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_0003"
down_revision: str | None = "20260811_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE search_history (
            id         UUID           NOT NULL DEFAULT gen_random_uuid(),
            owner_id   UUID           NOT NULL,
            video_id   UUID           NOT NULL,
            prompt     VARCHAR(300)   NOT NULL,
            clips      JSONB          NOT NULL DEFAULT '[]'::jsonb,
            expanded   BOOLEAN        NOT NULL DEFAULT false,
            min_score  DOUBLE PRECISION,
            created_at TIMESTAMPTZ    NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ    NOT NULL DEFAULT now(),
            CONSTRAINT pk_search_history PRIMARY KEY (id),
            CONSTRAINT fk_search_history_owner_id_users
                FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT fk_search_history_video_id_videos
                FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE
        )
    """)

    # Supports "list my history" and cascade cleanup per user / per video.
    op.execute("CREATE INDEX ix_search_history_owner_id ON search_history (owner_id)")
    op.execute("CREATE INDEX ix_search_history_video_id ON search_history (video_id)")


def downgrade() -> None:
    op.execute("DROP TABLE search_history")
