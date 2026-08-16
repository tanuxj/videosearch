"""In-app notifications — one row per event the user should see in the UI.

Today there is exactly one kind: ``indexed``, written by the indexing
pipeline when a video settles on ``status == "ready"`` (see
``app/videos/pipeline.py``). ``kind`` is a string rather than a boolean so
the bell can grow (transcript ready, a workspace invite, …) without a
migration.

Notifications are strictly per-user, addressed to the video's uploader. A
unique (user, video, kind) index makes the pipeline's write idempotent:
re-runs and the audio-only shortcut can't double-ring the bell.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# What a notification can be about. The pipeline writes `indexed`; add kinds
# here as the product grows.
NOTIFICATION_KINDS = ("indexed",)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Whose bell this rings. Cascades with the account.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # What it is about. Cascades with the video — a deleted video's
    # notification is meaningless.
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    # One of NOTIFICATION_KINDS.
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="indexed", server_default=text("'indexed'")
    )
    read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # The leftmost prefix (user_id) also serves list-by-user lookups, so
        # no separate user_id index is needed.
        Index(
            "uq_notifications_user_video_kind",
            "user_id",
            "video_id",
            "kind",
            unique=True,
        ),
        # So deleting a video cascades through an index instead of a seq scan.
        Index("ix_notifications_video_id", "video_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Notification user={self.user_id} video={self.video_id} "
            f"kind={self.kind} read={self.read}>"
        )
