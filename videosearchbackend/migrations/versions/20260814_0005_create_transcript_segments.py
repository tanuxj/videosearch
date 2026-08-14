"""create transcript_segments and video transcript columns

Revision ID: 20260814_0005
Revises: 20260814_0004
Create Date: 2026-08-14

Transcription schema:

* ``videos.transcript_status`` — the ASR job's own lifecycle, deliberately
  separate from ``videos.status``. Speech recognition finishes in seconds
  where CLIP frame embedding takes minutes, so a video is routinely
  ``status='processing'`` while ``transcript_status='ready'``.
  Existing rows backfill to ``'skipped'``: they were indexed before this
  feature existed and have no audio pass, so ``'pending'`` would leave them
  advertising a transcript that is never coming.
* ``videos.language`` — detected spoken language, used as the subtitle
  track's ``srclang``.
* ``transcript_segments`` — one row per timed utterance. Deleting a video
  cascades here.

Written as literal SQL (see 20260811_0001) — one statement per op.execute,
since asyncpg rejects multiple commands in a single prepared string.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_0005"
down_revision: str | None = "20260814_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Added with the 'pending' server default so new rows start there, but
    # backfilled to 'skipped' for videos that predate transcription.
    op.execute("""
        ALTER TABLE videos
            ADD COLUMN transcript_status VARCHAR(16) NOT NULL DEFAULT 'pending'
    """)
    op.execute("UPDATE videos SET transcript_status = 'skipped'")
    op.execute("ALTER TABLE videos ADD COLUMN transcript_error TEXT")
    op.execute("ALTER TABLE videos ADD COLUMN language VARCHAR(16)")
    op.execute("""
        ALTER TABLE videos
            ADD CONSTRAINT ck_videos_transcript_status
            CHECK (transcript_status IN
                ('pending', 'processing', 'ready', 'failed', 'skipped'))
    """)

    op.execute("""
        CREATE TABLE transcript_segments (
            id         UUID             NOT NULL DEFAULT gen_random_uuid(),
            video_id   UUID             NOT NULL,
            idx        INTEGER          NOT NULL,
            start_sec  DOUBLE PRECISION NOT NULL,
            end_sec    DOUBLE PRECISION NOT NULL,
            text       TEXT             NOT NULL,
            created_at TIMESTAMPTZ      NOT NULL DEFAULT now(),
            CONSTRAINT pk_transcript_segments PRIMARY KEY (id),
            CONSTRAINT fk_transcript_segments_video_id_videos
                FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE,
            CONSTRAINT uq_transcript_segments_video_id_idx UNIQUE (video_id, idx)
        )
    """)

    # Every read is "all segments for this video, in order" — the transcript
    # panel and the .vtt render alike.
    op.execute("CREATE INDEX ix_transcript_segments_video_id ON transcript_segments (video_id)")


def downgrade() -> None:
    op.execute("DROP TABLE transcript_segments")
    op.execute("ALTER TABLE videos DROP CONSTRAINT ck_videos_transcript_status")
    op.execute("ALTER TABLE videos DROP COLUMN language")
    op.execute("ALTER TABLE videos DROP COLUMN transcript_error")
    op.execute("ALTER TABLE videos DROP COLUMN transcript_status")
