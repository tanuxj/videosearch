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


class PresignUploadIn(BaseModel):
    """Metadata for a direct-to-storage upload.

    The file bytes never touch the API — it only validates the request and
    mints a presigned PUT URL for the browser to upload to.
    """

    filename: str
    size_bytes: int = Field(ge=0)
    content_type: str | None = None


class PresignUploadOut(BaseModel):
    """A reserved video plus the URL to PUT its file at.

    `upload_url` is None when the storage backend cannot presign (local
    disk) — clients then fall back to the classic multipart upload.
    """

    video: VideoOut
    upload_url: str | None
    expires_in: int = Field(description="Seconds the upload URL stays valid.")


class CompleteUploadOut(BaseModel):
    """Result of confirming a presigned upload."""

    video: VideoOut
    message: str = "Upload confirmed — indexing started"
