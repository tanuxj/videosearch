"""Search history: what the user searched, and what came back.

``search_history`` — one row per search the user ran. `clips` is an immutable
JSONB snapshot of the result they saw (`[{id, start, end, frame, score}, …]`),
not live frame rows, so the History page can show past searches and replay
their clips even though the frame index keeps evolving. Deleting a video
cascades here — a history entry is meaningless once its video is gone.
"""

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SearchRecord(Base, TimestampMixin):
    __tablename__ = "search_history"

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
    # Same cap as the search endpoint's `prompt` field (300 chars).
    prompt: Mapped[str] = mapped_column(String(300), nullable=False)
    # Snapshot of the search result, as returned by the frontend.
    clips: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Whether the backend expanded the prompt into visual variants.
    expanded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Backend's minimum-similarity threshold for this search, if known.
    min_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SearchRecord {self.prompt!r} video={self.video_id}>"
