"""Video library and frame index tables.

* ``videos`` — one row per uploaded video, owned by a user. `status` tracks
  the upload and indexing pipeline (`pending` → `processing` → `ready`, or
  `failed` with an error message). `storage_key` is the object key inside the R2 bucket (or the
  relative path under the local upload dir when R2 is not configured).
  `frames_total` / `frames_indexed` let the frontend show real progress.
* ``frames`` — one row per indexed frame, holding the CLIP image embedding
  (512 dims for clip-ViT-B-32) and the timestamp it came from. Search is a
  cosine-similarity query over `embedding`, accelerated by the HNSW index.
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

# `pending` = a row reserved for a direct-to-R2 upload that has not been
# confirmed yet. It becomes `processing` once the object is verified present
# in the bucket, or is swept away if the upload never lands.
VIDEO_STATUSES = ("pending", "processing", "ready", "failed")


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

    frames: Mapped[list["Frame"]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # A typo'd status must not silently insert — the pipeline only ever
        # writes VIDEO_STATUSES values.
        # The naming convention renders this as `ck_videos_status`.
        CheckConstraint(f"status IN {tuple(VIDEO_STATUSES)}", name="status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Video {self.name} status={self.status}>"


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
