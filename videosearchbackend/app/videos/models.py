"""Video library, frame index and saved-clip tables.

* ``videos`` — one row per uploaded video, owned by a user. `status` tracks
  the indexing pipeline (`processing` → `ready`, or `failed` with an error
  message). `storage_key` is the object key inside the R2 bucket (or the
  relative path under the local upload dir when R2 is not configured).
  `frames_total` / `frames_indexed` let the frontend show real progress.
* ``frames`` — one row per indexed frame, holding the CLIP image embedding
  (512 dims for clip-ViT-B-32) and the timestamp it came from. Search is a
  cosine-similarity query over `embedding`, accelerated by the HNSW index.
* ``saved_clips`` — scenes the user asked to keep: auto-extracted from a
  URL import that carried a prompt (see ``url_import.py``), stored as
  start/end/frame/score so the library can show them without a search.
* ``transcript_segments`` — the spoken audio as timed text, one row per
  segment. Written by ``transcribe.py``, which runs *alongside* frame
  embedding rather than after it: speech recognition finishes in seconds
  where CLIP takes minutes, so `transcript_status` is tracked separately
  from the video's `status` and the frontend can show subtitles while the
  visual index is still building.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# CLIP (clip-ViT-B-32) embeds both frames and text into this many dimensions.
EMBEDDING_DIM = 512

VIDEO_STATUSES = ("processing", "ready", "failed")

# Transcription runs on its own clock, so it has its own status:
# `skipped` — no ASR endpoint configured, or the video carries no audio track.
# `pending` → `processing` → `ready` / `failed` otherwise.
TRANSCRIPT_STATUSES = ("pending", "processing", "ready", "failed", "skipped")


class Video(Base, TimestampMixin):
    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Original filename — for display only; `storage_key` is what matters.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # One of VIDEO_STATUSES.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="processing", server_default=text("'processing'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # R2 object key (e.g. "{owner_id}/{video_id}.mp4") or local path.
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    poster_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    frames_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    frames_indexed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # One of TRANSCRIPT_STATUSES. Deliberately independent of `status`: a
    # video is commonly `status="processing"` (frames still embedding) while
    # `transcript_status="ready"`, which is the whole point — the text shows
    # up long before the visual index finishes.
    transcript_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'")
    )
    transcript_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Detected (or configured) spoken language, as an ISO-639-1 code where we
    # recognise it. Used as the subtitle track's `srclang`.
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)

    frames: Mapped[list["Frame"]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # A typo'd status must not silently insert — the pipeline only ever
        # writes VIDEO_STATUSES values.
        # The naming convention renders this as `ck_videos_status`.
        CheckConstraint(f"status IN {tuple(VIDEO_STATUSES)}", name="status"),
        CheckConstraint(
            f"transcript_status IN {tuple(TRANSCRIPT_STATUSES)}", name="transcript_status"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Video {self.name} status={self.status}>"


class SavedClip(Base, TimestampMixin):
    """A scene kept from an import, auto-extracted at index time.

    ``saved_clips`` — one row per kept scene. Created when a URL import carries
    a prompt: after indexing finishes, the import job runs the same CLIP search
    the search page uses and persists the best scenes, so the library can show
    them without a manual search. `frame` is the timestamp of the strongest
    matching frame (used for thumbnails), `score` its cosine similarity, and
    `start`/`end` span the padded scene exactly like a search result. Deleting
    a video cascades here.
    """

    __tablename__ = "saved_clips"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The prompt the scene was extracted for (same cap as search prompts).
    prompt: Mapped[str] = mapped_column(String(300), nullable=False)
    start: Mapped[float] = mapped_column(Float, nullable=False)
    # Quoted in DDL: `end` is a reserved word in PostgreSQL.
    end: Mapped[float] = mapped_column(Float, nullable=False)
    # Timestamp of the strongest matching frame — what thumbnails seek to.
    frame: Mapped[float] = mapped_column(Float, nullable=False)
    # Cosine similarity (0–1) of the strongest frame against the prompt.
    score: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SavedClip video={self.video_id} t={self.frame} score={self.score:.2f}>"


class TranscriptSegment(Base):
    """One timed line of speech, as returned by the ASR model.

    Segments are whole utterances (a few seconds each), not words — that is
    the granularity WebVTT cues and a readable transcript both want. `idx` is
    the segment's position in the video and is what ordering and the
    `(video_id, idx)` uniqueness both key on; ordering by `start_sec` would be
    ambiguous for the rare zero-length segment.
    """

    __tablename__ = "transcript_segments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Position in the video, 0-based. Chunked transcription re-numbers these
    # so they stay contiguous across chunk boundaries.
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    video: Mapped["Video"] = relationship(back_populates="transcript_segments")

    __table_args__ = (
        UniqueConstraint("video_id", "idx", name="uq_transcript_segments_video_id_idx"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TranscriptSegment video={self.video_id} t={self.start_sec}>"


class Frame(Base):
    __tablename__ = "frames"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Second the frame was extracted from (at 1 fps this is unique per video).
    timestamp_sec: Mapped[float] = mapped_column(Float, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    # R2 object key (or local path) of the thumbnail JPEG for this frame.
    thumb_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    video: Mapped["Video"] = relationship(back_populates="frames")

    __table_args__ = (
        # One frame per second, per video — duplicate extraction is a bug.
        UniqueConstraint("video_id", "timestamp_sec", name="uq_frames_video_id_timestamp_sec"),
        # Cosine-distance HNSW index for the similarity search. Declared here
        # (not just in the migration) so Alembic autogenerate/check stay in
        # sync with the database.
        Index(
            "ix_frames_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Frame video={self.video_id} t={self.timestamp_sec}>"
