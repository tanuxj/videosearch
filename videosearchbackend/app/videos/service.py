"""Video library business logic.

Kept free of FastAPI types: these functions raise domain errors and the route
layer decides which HTTP status each one maps to. The route layer also does
the heavy I/O on a threadpool, so the async service stays responsive.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.videos.models import Video
from app.videos.storage import storage

logger = logging.getLogger(__name__)
settings = get_settings()

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


class UploadNotCompleted(VideoError):
    """The client claimed an upload finished, but the object is not in storage."""


class UploadAlreadyCompleted(VideoError):
    """`complete` called on a video that has already left `pending`."""


class DirectUploadUnavailable(VideoError):
    """The active storage backend cannot presign uploads (local disk)."""


# Content types accepted for a direct PUT, keyed by extension. The presigned
# URL is signed *with* the content type, so the browser must send exactly this.
CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
}


def _safe_name(filename: str) -> str:
    """Basename only, truncated — the browser may send any string."""
    return Path(filename or "video.mp4").name[:255]


def _extension(filename: str) -> str:
    return Path(filename or "").suffix.lower()


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
) -> Video:
    """Persist an uploaded file and register its video row.

    Order matters: the file is written to storage *first*, then the row is
    inserted. If the insert fails the object is deleted again, so a failed
    upload never leaks an orphaned object.

    Note: FastAPI fully buffers the multipart body before this runs, so the
    size cap rejects after the transfer, not during it. True streaming
    limits would need manual body handling — fine for an MVP.
    """
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileType(ext)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise FileTooLarge(size_bytes)

    video_id = uuid.uuid4()
    key = object_key(owner_id, video_id, ext)
    # UploadFile.file is a sync SpooledTemporaryFile; boto3 wants a file-like
    # object, so the whole save runs on a worker thread.
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

    await db.refresh(video)
    logger.info("Video uploaded: %s (%d bytes, status=processing)", video.id, size_bytes)
    return video


@dataclass(slots=True)
class PendingUpload:
    """A reserved video row plus the URL the browser should PUT its bytes to."""

    video: Video
    upload_url: str
    content_type: str
    expires_in: int


async def create_pending_upload(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    filename: str,
    size_bytes: int,
) -> PendingUpload:
    """Reserve a video row and hand back a presigned PUT URL.

    No bytes touch the API: the browser uploads straight to R2 and the row
    stays `pending` until the object is confirmed present. The declared
    `size_bytes` is only used for the quota check here — the authoritative
    size is read back from storage in `complete_upload`.
    """
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileType(ext)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise FileTooLarge(size_bytes)
    if not storage.supports_direct_upload:
        raise DirectUploadUnavailable(storage.backend)

    video_id = uuid.uuid4()
    key = object_key(owner_id, video_id, ext)
    content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
    expires_in = settings.upload_url_ttl_seconds

    upload_url = await run_in_threadpool(storage.presign_put, key, content_type, expires_in)

    video = Video(
        id=video_id,
        owner_id=owner_id,
        name=_safe_name(filename),
        size_bytes=size_bytes,
        status="pending",
        storage_key=key,
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)

    return PendingUpload(
        video=video,
        upload_url=upload_url,
        content_type=content_type,
        expires_in=expires_in,
    )


async def complete_upload(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    video_id: uuid.UUID,
) -> Video:
    """Confirm a direct upload landed, then hand the video to the pipeline.

    The client calling this is only a hint. Storage is the source of truth: a
    PUT is atomic, so an object that exists is an upload that finished. The
    size recorded is the one storage reports, never the one the client claimed.
    """
    video = await get_video(db, owner_id, video_id)
    if video.status != "pending":
        # Already completed (or swept). Replaying must not re-trigger indexing.
        raise UploadAlreadyCompleted(video.status)

    head = await run_in_threadpool(storage.head, video.storage_key)
    if head is None:
        raise UploadNotCompleted(video.storage_key)

    size = int(head["size"])
    if size > MAX_UPLOAD_BYTES:
        # A presigned PUT cannot cap the body, so the limit is enforced here.
        logger.warning(
            "Direct upload for video %s exceeded the limit (%d bytes) — discarding",
            video.id,
            size,
        )
        await run_in_threadpool(storage.delete, video.storage_key)
        await db.delete(video)
        await db.commit()
        raise FileTooLarge(size)

    video.size_bytes = size
    video.status = "processing"
    await db.commit()
    await db.refresh(video)
    return video


async def sweep_pending_uploads(
    db: AsyncSession,
    *,
    older_than_minutes: int | None = None,
) -> tuple[list[uuid.UUID], int]:
    """Reconcile `pending` rows against storage. Returns (promoted, discarded).

    Covers the case the client can never report: the browser uploaded the file
    and then died before calling `complete` (closed tab, lost network). Asking
    storage settles it either way — object present means promote and index,
    absent means the upload never happened and the row goes.
    """
    minutes = (
        older_than_minutes
        if older_than_minutes is not None
        else settings.pending_upload_ttl_minutes
    )
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)

    result = await db.execute(
        select(Video).where(Video.status == "pending", Video.created_at < cutoff)
    )
    stale = list(result.scalars().all())
    if not stale:
        return [], 0

    promoted: list[uuid.UUID] = []
    discarded = 0

    for video in stale:
        head = await run_in_threadpool(storage.head, video.storage_key)
        if head is None:
            await db.delete(video)
            discarded += 1
            continue
        video.size_bytes = int(head["size"])
        video.status = "processing"
        promoted.append(video.id)

    await db.commit()
    logger.info("Swept pending uploads: %d promoted, %d discarded", len(promoted), discarded)
    return promoted, discarded


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
