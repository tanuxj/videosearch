"""Request and response models for the video routes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VideoOut(BaseModel):
    """Public view of a video — never exposes the storage key or path."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    size_bytes: int
    duration_seconds: float | None = None
    status: str
    error: str | None = None
    frames_total: int
    frames_indexed: int
    created_at: datetime
    updated_at: datetime


class VideoListOut(BaseModel):
    items: list[VideoOut]
    count: int = Field(description="Number of videos returned.")


class StreamUrlOut(BaseModel):
    """A playback URL for a video.

    `worker=true` means the URL points at the edge streaming Worker and is
    signed (short-lived); `worker=false` is the classic API-proxied stream.
    """

    url: str
    worker: bool
