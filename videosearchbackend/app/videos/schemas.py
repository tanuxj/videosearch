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


class UploadUrlIn(BaseModel):
    """Details of the file the client is about to upload directly to storage."""

    filename: str = Field(min_length=1, max_length=255, examples=["holiday.mp4"])
    size_bytes: int = Field(ge=1, examples=[36_806_638], description="Client-reported size.")


class UploadUrlOut(BaseModel):
    """Where and how to PUT the bytes.

    `direct=false` means this deployment cannot presign (local-disk storage) —
    the client should fall back to `POST /videos` multipart instead.
    """

    direct: bool
    video_id: uuid.UUID | None = None
    upload_url: str | None = None
    method: str = "PUT"
    # The presigned URL is signed with this content type, so the PUT must send
    # exactly this value or storage rejects the signature.
    content_type: str | None = None
    expires_in: int | None = Field(default=None, description="URL lifetime in seconds.")


class StreamUrlOut(BaseModel):
    """A playback URL for a video.

    `worker=true` means the URL points at the edge streaming Worker and is
    signed (short-lived); `worker=false` is the classic API-proxied stream.
    """

    url: str
    worker: bool
