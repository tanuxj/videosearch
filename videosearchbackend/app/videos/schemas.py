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
    # The workspace this video lives in, or null for the uploader's personal
    # library. The frontend uses it to tag shared videos and scope the
    # library view.
    workspace_id: uuid.UUID | None = None
    # How the video entered the library — `upload` | `recording` | `url`.
    # The frontend tags recordings with it so they read differently from
    # plain uploads in the library.
    source: str = "upload"
    error: str | None = None
    # Whether the file has a video track. False for audio-only recordings
    # (nothing to frame-index — the frontend keeps them out of search); null
    # until the pipeline has probed the file.
    has_video: bool | None = None
    frames_total: int
    frames_indexed: int
    # Transcription's own lifecycle — `pending` | `processing` | `ready` |
    # `failed` | `skipped`. Reaches `ready` well before `status` does, which is
    # how the client knows it can show subtitles mid-index.
    transcript_status: str
    # Detected spoken language (ISO-639-1 where recognised), once known.
    language: str | None = None
    # Collections this video is filed in. Populated by the list endpoint from
    # one batched query; empty on the single-video routes, which don't pay for
    # the extra lookup.
    collection_ids: list[uuid.UUID] = []
    # Deletion deadline for homepage-trial uploads; null for permanent
    # videos. The demo UI counts down to it; the purge sweep enforces it.
    expires_at: datetime | None = None
    # How long indexing took, and when it ran. `processing_seconds` is null
    # in exactly two cases the client must tell apart: indexing is still
    # running (count up from `processing_started_at` for a live timer), or
    # the video predates the timing columns (show nothing).
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    processing_seconds: float | None = None
    created_at: datetime
    updated_at: datetime


class VideoListOut(BaseModel):
    items: list[VideoOut]
    count: int = Field(description="Number of videos returned.")


class ShareLinkOut(BaseModel):
    """The share link for a video, minted lazily on first request.

    `url` is the app-relative share path (`/share/<token>`) — the frontend
    prefixes its own origin. The token is unguessable and survives on the row,
    so asking again returns the same link instead of a new one; unsharing
    clears it and revokes every outstanding link.
    """

    token: str
    url: str = Field(description="App-relative share path, e.g. `/share/abc…`.")


class PublicShareOut(BaseModel):
    """What the public share page may know about a video.

    Deliberately a subset of `VideoOut` — no owner id, no error internals, no
    collection membership. `stream_url` is the public, Range-aware playback
    path so the share page can hand it straight to a `<video>` element.
    """

    id: uuid.UUID
    name: str
    duration_seconds: float | None = None
    status: str
    # How the video entered the library — `upload` | `recording` | `url`.
    source: str = "upload"
    has_video: bool | None = None
    transcript_status: str
    language: str | None = None
    created_at: datetime
    stream_url: str


class StreamUrlOut(BaseModel):
    """A playback URL for a video.

    `worker=true` means the URL points at the edge streaming Worker and is
    signed (short-lived); `worker=false` is the classic API-proxied stream.
    """

    url: str
    worker: bool


class VideoMoveIn(BaseModel):
    """Move a video between workspaces (or back to the uploader's library).

    `workspace_id: null` moves the video back to the uploader's personal
    library. The caller must be able to edit the video and, when the target
    is a workspace, be an editor of it.
    """

    workspace_id: uuid.UUID | None = None


class UrlImportIn(BaseModel):
    """A link to a video to download and index.

    Accepts YouTube/Twitch/Zoom/Vimeo links (resolved with yt-dlp) or a
    direct video file URL. Scheme and host are validated server-side (SSRF
    guard) before anything is downloaded. When `prompt` is set, the best
    `clip_limit` matching scenes are auto-saved as clips after indexing.
    """

    url: str = Field(
        min_length=1,
        max_length=2048,
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )
    # Optional: auto-save the scenes that match this description once the
    # video is indexed, so the library shows highlights without a manual search.
    prompt: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        examples=["a red car driving on a highway"],
    )
    # How many top scenes to keep when `prompt` is set (0 disables auto-save).
    clip_limit: int = Field(default=3, ge=0, le=9)
    # Upload into a workspace instead of the uploader's personal library.
    workspace_id: uuid.UUID | None = None


class UrlImportBatchIn(BaseModel):
    """Many links to download and index at once.

    Each URL — or each video inside a playlist/channel link — becomes its own
    `processing` video and is downloaded + indexed in the background. Every
    link is validated and probed individually; failures are reported per URL
    in the response instead of failing the whole batch. A shared `prompt`
    auto-saves the best matching scenes on every video in the batch.
    """

    urls: list[str] = Field(
        min_length=1,
        max_length=100,
        examples=[["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]],
    )
    prompt: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        examples=["a red car driving on a highway"],
    )
    clip_limit: int = Field(default=3, ge=0, le=9)
    # Upload into a workspace instead of the uploader's personal library.
    workspace_id: uuid.UUID | None = None


class UrlImportItem(BaseModel):
    """Outcome for one target URL in a batch import.

    Either `video` (the reserved, now-importing row) or `error` (why that
    link was skipped) — never both.
    """

    url: str
    video: VideoOut | None = None
    error: str | None = None


class UrlImportBatchOut(BaseModel):
    """Result of a batch import, one item per resolved target URL."""

    items: list[UrlImportItem]
    total: int = Field(description="Number of videos successfully reserved.")


class SavedClipOut(BaseModel):
    """A scene kept from an import — same shape a search result uses.

    `frame` is the strongest matching frame's timestamp (thumbnails seek to
    it); `score` its cosine similarity (0–1) against the prompt.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prompt: str
    start: float
    end: float
    frame: float
    score: float
    created_at: datetime


class SavedClipListOut(BaseModel):
    items: list[SavedClipOut]
    count: int = Field(description="Number of saved clips returned.")


class TranscriptSegmentOut(BaseModel):
    """One timed line of speech.

    Named `start`/`end` to match the clip shape the frontend already consumes;
    the route maps them from the model's `start_sec`/`end_sec`.
    """

    start: float = Field(description="Seconds into the video.")
    end: float
    text: str


class TranscriptOut(BaseModel):
    """A video's spoken content as timed text.

    `status` mirrors the video's `transcript_status`, so a client polling this
    endpoint can tell "not done yet" (`processing`) from "there will never be
    one" (`skipped` — no audio track, or no ASR endpoint configured).
    `segments` is empty for every status but `ready`.
    """

    status: str
    language: str | None = None
    error: str | None = None
    segments: list[TranscriptSegmentOut]
    count: int = Field(description="Number of transcript segments.")


class PresignUploadIn(BaseModel):
    """Metadata for a direct-to-storage upload.

    The file bytes never touch the API — it only validates the request and
    mints a presigned PUT URL for the browser to upload to.
    """

    filename: str
    size_bytes: int = Field(ge=0)
    content_type: str | None = None
    # How the upload should be labelled — the Record tab sends `recording` so
    # its saves are tagged in the library. Whitelisted to the same values the
    # column check constraint accepts.
    source: str = Field(default="upload", pattern="^(upload|recording|url)$")
    # Upload into a workspace instead of the uploader's personal library.
    # The caller must be an editor (owner/admin/member) of that workspace.
    workspace_id: uuid.UUID | None = None


class PresignUploadOut(BaseModel):
    """A reserved video plus the URL to PUT its file at.

    `upload_url` is None when the storage backend cannot presign (local
    disk) — clients then fall back to the classic multipart upload.
    """

    video: VideoOut
    upload_url: str | None
    expires_in: int = Field(description="Seconds the upload URL stays valid.")


class MultipartPartOut(BaseModel):
    """One presigned PUT URL for a single chunk of a multipart upload."""

    part_number: int
    url: str


class PresignMultipartOut(BaseModel):
    """A reserved video plus per-chunk URLs for a multipart upload.

    Used for files larger than the 5 GiB single-PUT cap: the browser slices
    the file into `part_size`-byte chunks, PUTs each to its own URL (reusing
    the same authentication the API mints), then calls
    `POST /videos/{id}/complete/multipart` with the returned ETags.
    """

    video: VideoOut
    upload_id: str
    part_size: int = Field(description="Chunk size in bytes; the last chunk may be smaller.")
    parts: list[MultipartPartOut]
    expires_in: int = Field(description="Seconds the part URLs stay valid.")


class MultipartPartIn(BaseModel):
    """An uploaded chunk, as returned in the PUT response's ETag header."""

    part_number: int = Field(ge=1)
    etag: str = Field(min_length=1)


class CompleteMultipartIn(BaseModel):
    """Chunks to assemble into the final object."""

    upload_id: str = Field(min_length=1)
    parts: list[MultipartPartIn] = Field(min_length=1)


class CompleteUploadOut(BaseModel):
    """Result of confirming a presigned upload."""

    video: VideoOut
    message: str = "Upload confirmed — indexing started"
