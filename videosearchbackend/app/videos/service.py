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

from app.videos.models import Video
from app.videos.storage import storage

logger = logging.getLogger(__name__)

# Matches the frontend's client-side cap (512 MiB).
MAX_UPLOAD_BYTES = 512 * 1024 * 1024

# Extensions the pipeline knows how to index. The upload handler rejects
# anything else before a single byte hits storage.
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}


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


async def list_videos(db: AsyncSession, owner_id: uuid.UUID) -> list[Video]:
    result = await db.execute(
        select(Video).where(Video.owner_id == owner_id).order_by(Video.created_at.desc())
    )
    return list(result.scalars())


async def get_video(db: AsyncSession, owner_id: uuid.UUID, video_id: uuid.UUID) -> Video:
    """Fetch a video, enforcing ownership (404 either way)."""
    video = await db.get(Video, video_id)
    if video is None or video.owner_id != owner_id:
        raise VideoNotFound(video_id)
    return video


async def delete_video(db: AsyncSession, owner_id: uuid.UUID, video_id: uuid.UUID) -> None:
    """Remove the row (cascades to frames) and its stored object."""
    video = await get_video(db, owner_id, video_id)
    await db.delete(video)
    await db.commit()
    await run_in_threadpool(storage.delete, video.storage_key)
    logger.info("Video deleted: %s", video_id)
