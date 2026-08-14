"""reconcile transcript schema, preserving existing segments

Revision ID: 20260814_0006
Revises: 20260814_0005
Create Date: 2026-08-14

Why this exists
---------------
An earlier transcription attempt applied its own migration stamped
``20260814_0005`` to development databases and then lost its source (only a
stale ``app/videos/__pycache__/transcription.cpython-312.pyc`` survives). Its
schema differs from the one ``20260814_0005`` in this repo creates:

    videos              index_phase, transcript_language
    transcript_segments start, "end", language   (no idx)

So a dev database can be stamped ``0005`` while carrying a schema the ORM does
not recognise — and with real transcripts in it. This revision converts that
shape into the current one **without dropping a single segment row**: `start`
and `end` are renamed rather than recreated, and `idx` is backfilled from each
video's existing ordering.

Every step is guarded on what is actually present, because the same revision
has to be a no-op on a database that took this repo's ``0005`` (where the
schema is already correct) and a conversion on one that took the ghost. Guards
live inside ``DO`` blocks: a single statement each, which is what asyncpg
requires (see 20260811_0001).

The one deliberate loss is ``transcript_segments.language``. It was per-segment
and, in the observed data, identical across every row of a video — the
language belongs on the video, which is where it now lives.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_0006"
down_revision: str | None = "20260814_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── videos ────────────────────────────────────────────────
    # The ghost tracked progress in `index_phase`; this schema splits the two
    # lifecycles into `status` (frames) and `transcript_status` (text).
    op.execute("ALTER TABLE videos DROP COLUMN IF EXISTS index_phase")
    op.execute("""
        ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS transcript_status VARCHAR(16)
                NOT NULL DEFAULT 'pending'
    """)
    op.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS transcript_error TEXT")

    # `transcript_language` → `language`, but only when that is the shape we
    # actually find: a database from this repo's 0005 already has `language`.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'videos' AND column_name = 'transcript_language'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'videos' AND column_name = 'language'
            ) THEN
                ALTER TABLE videos RENAME COLUMN transcript_language TO language;
            END IF;
        END $$
    """)
    op.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS language VARCHAR(16)")
    # A leftover `transcript_language` can only exist if `language` was already
    # there too, in which case it is redundant.
    op.execute("ALTER TABLE videos DROP COLUMN IF EXISTS transcript_language")

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_videos_transcript_status'
            ) THEN
                ALTER TABLE videos
                    ADD CONSTRAINT ck_videos_transcript_status
                    CHECK (transcript_status IN
                        ('pending', 'processing', 'ready', 'failed', 'skipped'));
            END IF;
        END $$
    """)

    # ── transcript_segments ───────────────────────────────────
    # Renames, never a drop-and-recreate: the rows are the user's transcripts.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'transcript_segments' AND column_name = 'start'
            ) THEN
                ALTER TABLE transcript_segments RENAME COLUMN start TO start_sec;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'transcript_segments' AND column_name = 'end'
            ) THEN
                ALTER TABLE transcript_segments RENAME COLUMN "end" TO end_sec;
            END IF;
        END $$
    """)

    op.execute("""
        ALTER TABLE transcript_segments
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """)
    op.execute("ALTER TABLE transcript_segments ADD COLUMN IF NOT EXISTS idx INTEGER")

    # Backfill ordering from what the ghost stored: position by start time
    # within each video, which is the order the segments were spoken in.
    op.execute("""
        UPDATE transcript_segments AS t
        SET idx = numbered.position
        FROM (
            SELECT id,
                   (row_number() OVER (PARTITION BY video_id ORDER BY start_sec, id) - 1)
                       AS position
            FROM transcript_segments
        ) AS numbered
        WHERE t.id = numbered.id AND t.idx IS NULL
    """)
    op.execute("ALTER TABLE transcript_segments ALTER COLUMN idx SET NOT NULL")

    # Per-segment language is redundant once it lives on the video.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'transcript_segments' AND column_name = 'language'
            ) THEN
                -- Carry it up to any video that has not got one yet, then drop.
                UPDATE videos AS v
                SET language = s.language
                FROM (
                    SELECT DISTINCT ON (video_id) video_id, language
                    FROM transcript_segments
                    ORDER BY video_id, start_sec
                ) AS s
                WHERE v.id = s.video_id AND v.language IS NULL;

                ALTER TABLE transcript_segments DROP COLUMN language;
            END IF;
        END $$
    """)

    # The ghost's uniqueness was (video_id, start); ours is (video_id, idx).
    op.execute("""
        ALTER TABLE transcript_segments
            DROP CONSTRAINT IF EXISTS uq_transcript_segments_video_id_start
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_transcript_segments_video_id_idx'
            ) THEN
                ALTER TABLE transcript_segments
                    ADD CONSTRAINT uq_transcript_segments_video_id_idx
                    UNIQUE (video_id, idx);
            END IF;
        END $$
    """)

    # ── settle transcript_status against reality ──────────────
    # A video that already has segments is `ready` — its transcript is right
    # there. One that does not was indexed before transcription existed and
    # will never get a pass, so `skipped` stops the frontend polling forever.
    op.execute("""
        UPDATE videos SET transcript_status = 'ready'
        WHERE EXISTS (SELECT 1 FROM transcript_segments s WHERE s.video_id = videos.id)
    """)
    op.execute("""
        UPDATE videos SET transcript_status = 'skipped'
        WHERE transcript_status = 'pending'
          AND NOT EXISTS (SELECT 1 FROM transcript_segments s WHERE s.video_id = videos.id)
    """)


def downgrade() -> None:
    # Back to this repo's 0005 shape, not the ghost's — that schema has no
    # source left to run against and reviving it would help nobody. Segment
    # rows survive the round trip; `idx` ordering is what `start` gave us.
    op.execute("""
        ALTER TABLE transcript_segments
            DROP CONSTRAINT IF EXISTS uq_transcript_segments_video_id_idx
    """)
    op.execute("""
        ALTER TABLE transcript_segments
            ADD CONSTRAINT uq_transcript_segments_video_id_idx UNIQUE (video_id, idx)
    """)
    op.execute("ALTER TABLE videos DROP CONSTRAINT IF EXISTS ck_videos_transcript_status")
    op.execute("""
        ALTER TABLE videos
            ADD CONSTRAINT ck_videos_transcript_status
            CHECK (transcript_status IN
                ('pending', 'processing', 'ready', 'failed', 'skipped'))
    """)
