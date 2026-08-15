"""Video library business logic.

Kept free of FastAPI types: these functions raise domain errors and the route
layer decides which HTTP status each one maps to. The route layer also does
the heavy I/O on a threadpool, so the async service stays responsive.
"""

import logging
import uuid
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import CollectionVideo
from app.core.config import get_settings
from app.videos.models import TranscriptSegment, Video
from app.videos.storage import storage

logger = logging.getLogger(__name__)

# Matches the frontend's client-side cap. Read from settings so it is
# configurable at deploy time (MAX_UPLOAD_BYTES); kept as a module-level name
# so tests can monkeypatch it directly.
MAX_UPLOAD_BYTES = get_settings().max_upload_bytes

# Extensions the pipeline knows how to index. The upload handler rejects
# anything else before a single byte hits storage.
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

# Content types for the containers the pipeline can index. Used when storing
# and streaming a video; URL imports pick from the same map so an imported
# file streams with the right type.
MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".m4v": "video/x-m4v",
}


class VideoError(Exception):
    """Base class for video library failures."""


class VideoNotFound(VideoError):
    """No such video, or it belongs to someone else (same 404)."""


class UnsupportedFileType(VideoError):
    pass


class FileTooLarge(VideoError):
    pass


class UploadNotComplete(VideoError):
    """A presigned upload was reserved but its bytes never landed."""


class UploadSizeMismatch(VideoError):
    """The uploaded object's size does not match what was declared."""

    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(f"expected {expected} bytes, got {actual}")
        self.expected = expected
        self.actual = actual


def _safe_name(filename: str) -> str:
    """Basename only, truncated — the browser may send any string."""
    return Path(filename or "video.mp4").name[:255]


def _extension(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def validate_upload(filename: str, size_bytes: int) -> str:
    """Reject unsupported extensions and oversize files; return the ext.

    Shared by the multipart upload and the presigned-upload reservation so
    both entry points enforce exactly the same rules.
    """
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileType(ext)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise FileTooLarge(size_bytes)
    return ext


def object_key(owner_id: uuid.UUID, video_id: uuid.UUID, ext: str) -> str:
    """Storage key layout: `<owner>/<video><ext>` — flat per user, unique per video."""
    return f"{owner_id}/{video_id}{ext}"


async def create_video(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    filename: str,
    size_bytes: int,
    content_type: str | None,
    file,
) -> tuple[Video, Path | None]:
    """Persist an uploaded file and register its video row.

    Returns `(video, staged_path)`. `staged_path` is a local copy of the bytes
    kept for the indexing pipeline so it does not download the object that was
    just uploaded; it is None when the backend is already local. **The caller
    owns that file** and must delete it (the pipeline does).

    Order matters: the file is written to storage *first*, then the row is
    inserted. If the insert fails the object is deleted again, so a failed
    upload never leaks an orphaned object.

    Note: FastAPI fully buffers the multipart body before this runs, so the
    size cap rejects after the transfer, not during it. True streaming
    limits would need manual body handling — fine for an MVP.
    """
    ext = validate_upload(filename, size_bytes)
    key = object_key(owner_id, uuid.uuid4(), ext)

    # Stage to local disk before uploading, not after: boto3 closes the file
    # object it reads from, so the bytes are unrecoverable once the upload has
    # run. Skipped for the local backend, where the stored file is already a
    # readable local path.
    staged_path: Path | None = None
    if storage.backend == "r2":
        staged_path = await run_in_threadpool(storage.spill_to_temp, file, ext)

    try:
        if staged_path is not None:
            await run_in_threadpool(storage.save_path, key, staged_path, content_type)
        else:
            # UploadFile.file is a sync SpooledTemporaryFile; boto3 wants a
            # file-like object, so the whole save runs on a worker thread.
            await run_in_threadpool(storage.save_file, key, file, content_type)

        video = Video(
            owner_id=owner_id,
            name=_safe_name(filename),
            size_bytes=size_bytes,
            status="processing",
            storage_key=key,
        )
        db.add(video)
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            # Don't leave a file behind with no row pointing at it.
            await run_in_threadpool(storage.delete, key)
            raise
    except Exception:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        raise

    await db.refresh(video)
    logger.info("Video uploaded: %s (%d bytes, status=processing)", video.id, size_bytes)
    return video, staged_path


def display_name(title: str, ext: str) -> str:
    """A user-facing name from a download title and container extension.

    Truncated like every other stored name. Avoids doubling the extension
    when the title already carries it (direct file probes name the file after
    the URL path, e.g. "clip.mp4").
    """
    name = (title or "video").strip() or "video"
    ext = (ext or "").lower().lstrip(".")
    if ext and not name.lower().endswith(f".{ext}"):
        name = f"{name}.{ext}"
    return _safe_name(name)


async def create_url_video(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    title: str,
    ext: str,
) -> Video:
    """Reserve a `processing` video row for a URL import.

    The storage key uses the extension the metadata probe reported; the
    background download adjusts it if the real container differs (nothing has
    been stored under the key yet). `size_bytes` starts at 0 and is filled in
    once the download lands.
    """
    ext = (ext or "mp4").lower().lstrip(".") or "mp4"
    video_id = uuid.uuid4()
    video = Video(
        owner_id=owner_id,
        name=display_name(title, ext),
        size_bytes=0,
        status="processing",
        storage_key=object_key(owner_id, video_id, ext),
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)
    logger.info("Video reserved for URL import: %s (ext=%s)", video.id, ext)
    return video


async def create_pending_video(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    filename: str,
    size_bytes: int,
) -> Video:
    """Reserve a `processing` video row before its bytes arrive.

    Presigned-upload flow: the API mints a PUT URL pointing straight at the
    object key this row owns, and the browser uploads the file itself — the
    API never buffers a large multipart body. The caller is expected to hand
    the row over to `complete_pending_video` once the object lands.
    """
    validate_upload(filename, size_bytes)

    video_id = uuid.uuid4()
    key = object_key(owner_id, video_id, _extension(filename))
    video = Video(
        owner_id=owner_id,
        name=_safe_name(filename),
        size_bytes=size_bytes,
        status="processing",
        storage_key=key,
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)
    logger.info(
        "Video reserved for presigned upload: %s (%d bytes)",
        video.id,
        size_bytes,
    )
    return video


async def complete_pending_video(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    video_id: uuid.UUID,
    expected_bytes: int,
) -> Video:
    """Verify a presigned upload landed and finish the reservation.

    Checks the object really exists in storage and matches the declared
    size before the pipeline may start — a client that mints a URL but never
    PUTs the file (or lies about its size) fails fast instead of leaving the
    row stuck in `processing`.

    Returns the confirmed video; the route layer then starts indexing.
    """
    video = await get_video(db, owner_id, video_id)

    actual = await run_in_threadpool(storage.object_size, video.storage_key)
    if actual is None:
        raise UploadNotComplete("file was never uploaded")
    if actual != expected_bytes:
        raise UploadSizeMismatch(expected=expected_bytes, actual=actual)

    logger.info("Presigned upload confirmed: %s (%d bytes)", video.id, actual)
    return video


async def list_videos(
    db: AsyncSession,
    owner_id: uuid.UUID,
    *,
    collection_id: uuid.UUID | None = None,
) -> list[Video]:
    """The user's videos, newest first, optionally narrowed to one collection.

    An unknown or someone else's `collection_id` yields an empty list rather
    than an error: the join finds no membership rows, and the `owner_id` filter
    means a leaked id can never widen the result past the caller's own library.
    """
    query = select(Video).where(Video.owner_id == owner_id)
    if collection_id is not None:
        query = query.join(CollectionVideo, CollectionVideo.video_id == Video.id).where(
            CollectionVideo.collection_id == collection_id
        )
    result = await db.execute(query.order_by(Video.created_at.desc()))
    return list(result.scalars())


async def get_video(db: AsyncSession, owner_id: uuid.UUID, video_id: uuid.UUID) -> Video:
    """Fetch a video, enforcing ownership (404 either way)."""
    video = await db.get(Video, video_id)
    if video is None or video.owner_id != owner_id:
        raise VideoNotFound(video_id)
    return video


async def list_transcript_segments(
    db: AsyncSession, video_id: uuid.UUID
) -> list[TranscriptSegment]:
    """Every transcript line for a video, in playback order.

    Ordered by `idx` rather than `start_sec`: chunked transcription numbers
    segments contiguously across chunk boundaries, and two cues can share a
    start time when a chunk seam falls mid-sentence.
    """
    result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.video_id == video_id)
        .order_by(TranscriptSegment.idx)
    )
    return list(result.scalars())


async def delete_video(db: AsyncSession, owner_id: uuid.UUID, video_id: uuid.UUID) -> None:
    """Remove the row (cascades to frames and transcript segments) and its object."""
    video = await get_video(db, owner_id, video_id)
    await db.delete(video)
    await db.commit()
    await run_in_threadpool(storage.delete, video.storage_key)
    logger.info("Video deleted: %s", video_id)
