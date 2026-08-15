"""Collections: user-made groupings of videos.

* ``collections`` — one row per named group, owned by a user.
* ``collection_videos`` — the membership join. Many-to-many on purpose: a
  video belongs to as many collections as the user likes, which is what lets
  one feature cover both folders (a video's home) and tags (several labels on
  the same video) instead of shipping two. The composite primary key makes
  re-adding a video a no-op in the database rather than a duplicate row.

Cascade rules are deliberate. Deleting a user drops their collections;
deleting a *collection* or a *video* drops only the membership rows. Emptying
a collection must never delete the footage inside it — the videos outlive
however the user chose to file them.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Longest collection name. Mirrored by the API schema's `max_length`.
NAME_MAX_LENGTH = 120


class Collection(Base, TimestampMixin):
    __tablename__ = "collections"

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
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)

    __table_args__ = (
        # Unique on `lower(name)`, not `name`: two sidebar entries reading
        # "Lectures" and "lectures" are indistinguishable at a glance, so the
        # second one is a mistake worth rejecting rather than a distinct
        # collection the user meant to create.
        Index(
            "uq_collections_owner_id_lower_name",
            "owner_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Collection {self.name!r} owner={self.owner_id}>"


class CollectionVideo(Base):
    """One video's membership in one collection.

    No surrogate key: `(collection_id, video_id)` *is* the identity, and making
    it the primary key is what lets ``add_videos`` insert with
    ``ON CONFLICT DO NOTHING`` and stay idempotent.
    """

    __tablename__ = "collection_videos"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("collections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # The primary key already covers collection → videos. This one covers
        # the reverse — "which collections is this video in" — which is what
        # the library grid asks for once per page load.
        Index("ix_collection_videos_video_id", "video_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CollectionVideo collection={self.collection_id} video={self.video_id}>"
