"""Video library business logic.

Kept free of FastAPI types: these functions raise domain errors and the route
layer decides which HTTP status each one maps to. The route layer also does
the heavy I/O on a threadpool, so the async service stays responsive.
"""

import logging
import secrets
import uuid
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.guest import apply_trial_expiry
from app.collections.models import CollectionVideo
from app.core.config import get_settings
from app.videos.models import VIDEO_SOURCES, TranscriptSegment, Video
from app.videos.storage import storage
from app.workspaces import service as workspaces_service

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


def _valid_source(source: str) -> str:
    """Coerce a caller-supplied source to a known value.

    The database check constraint rejects anything else at insert time, but a
    500 from a constraint violation is a worse answer than quietly falling
    back to `upload` — a stale client sending an unknown label is not a reason
    to fail the upload.
    """
    return source if source in VIDEO_SOURCES else "upload"


async def _require_workspace_editor(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID | None
) -> None:
    """Raise `VideoForbidden` unless the caller may upload into the workspace.

    A non-member (or a viewer) uploading into a shared workspace would write
    footage the workspace never agreed to host — or, worse, leak into it.
    The uploader's own library (null) needs no check.
    """
    if workspace_id is None:
        return
    role = await workspaces_service.member_role(db, workspace_id, user_id)
    if not workspaces_service.can_edit_videos(role):
        raise VideoForbidden(workspace_id)


async def create_video(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    filename: str,
    size_bytes: int,
    content_type: str | None,
    source: str = "upload",
    workspace_id: uuid.UUID | None = None,
    file,
    trial: bool = False,
) -> tuple[Video, Path | None]:
    """Persist an uploaded file and register its video row.

    Returns `(video, staged_path)`. `staged_path` is a local copy of the bytes
    kept for the indexing pipeline so it does not download the object that was
    just uploaded; it is None when the backend is already local. **The caller
    owns that file** and must delete it (the pipeline does).

    Uploading into a workspace requires an editor role there (owner/admin/
    member) — checked before a single byte is stored.

    Order matters: the file is written to storage *first*, then the row is
    inserted. If the insert fails the object is deleted again, so a failed
    upload never leaks an orphaned object.

    Note: FastAPI fully buffers the multipart body before this runs, so the
    size cap rejects after the transfer, not during it. True streaming
    limits would need manual body handling — fine for an MVP.
    """
    ext = validate_upload(filename, size_bytes)
    await _require_workspace_editor(db, owner_id, workspace_id)
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
            workspace_id=workspace_id,
            name=_safe_name(filename),
            size_bytes=size_bytes,
            status="processing",
            source=_valid_source(source),
            storage_key=key,
        )
        # Homepage-trial uploads are stamped with their deletion deadline
        # here — a no-op for registered accounts and when trials are off.
        apply_trial_expiry(video, get_settings(), trial=trial)
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
    size_bytes: int = 0,
    duration_seconds: float = 0.0,
    workspace_id: uuid.UUID | None = None,
    trial: bool = False,
) -> Video:
    await _require_workspace_editor(db, owner_id, workspace_id)
    """Reserve a `processing` video row for a URL import.

    The storage key uses the extension the metadata probe reported; the
    background download adjusts it if the real container differs (nothing has
    been stored under the key yet).

    `size_bytes` and `duration_seconds` are the probe's figures, so the library
    row reads as a real video straight away rather than "0 B" for the length of
    the download. Both are replaced with measured values once the file lands —
    the probe's size is an estimate, and some hosts report neither.
    """
    ext = (ext or "mp4").lower().lstrip(".") or "mp4"
    video_id = uuid.uuid4()
    video = Video(
        owner_id=owner_id,
        workspace_id=workspace_id,
        name=display_name(title, ext),
        size_bytes=max(0, size_bytes or 0),
        duration_seconds=max(0.0, duration_seconds or 0.0),
        status="processing",
        source="url",
        storage_key=object_key(owner_id, video_id, ext),
    )
    # Trial imports expire on the same clock as trial uploads.
    apply_trial_expiry(video, get_settings(), trial=trial)
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
    source: str = "upload",
    workspace_id: uuid.UUID | None = None,
    trial: bool = False,
) -> Video:
    await _require_workspace_editor(db, owner_id, workspace_id)
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
        workspace_id=workspace_id,
        name=_safe_name(filename),
        size_bytes=size_bytes,
        status="processing",
        source=_valid_source(source),
        storage_key=key,
    )
    # Same trial stamping as the multipart upload path.
    apply_trial_expiry(video, get_settings(), trial=trial)
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
    workspace_id: uuid.UUID | None = None,
) -> list[Video]:
    """The user's videos, newest first, optionally narrowed.

    Without `workspace_id`: the user's personal library plus every video in
    the workspaces they belong to. With it: only that workspace's videos
    (empty when the caller isn't a member — a leaked id can never widen the
    result). `collection_id` narrows further, and its membership join can
    never leak another user's library because the scope filter is applied
    first.
    """
    if workspace_id is not None:
        if not await workspaces_service.is_member(db, workspace_id, owner_id):
            return []
        query = select(Video).where(Video.workspace_id == workspace_id)
    else:
        workspace_ids = await workspaces_service.accessible_workspace_ids(db, owner_id)
        query = select(Video).where(
            or_(
                Video.owner_id == owner_id,
                Video.workspace_id.in_(workspace_ids) if workspace_ids else False,
            )
        )
    if collection_id is not None:
        query = query.join(CollectionVideo, CollectionVideo.video_id == Video.id).where(
            CollectionVideo.collection_id == collection_id
        )
    result = await db.execute(query.order_by(Video.created_at.desc()))
    return list(result.scalars())


async def get_video(db: AsyncSession, owner_id: uuid.UUID, video_id: uuid.UUID) -> Video:
    """Fetch a video the user may see — owner or workspace member (404 either way).

    The membership lookup is a single indexed query, cheap enough for every
    route that resolves a video by id (stream, transcript, search, share,
    delete).
    """
    video = await db.get(Video, video_id)
    if video is None:
        raise VideoNotFound(video_id)
    if video.owner_id == owner_id:
        return video
    if video.workspace_id is not None and await workspaces_service.is_member(
        db, video.workspace_id, owner_id
    ):
        return video
    raise VideoNotFound(video_id)


async def get_or_create_share_token(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    video_id: uuid.UUID,
) -> str:
    """The video's share token, minting it on first request.

    Sharing is opt-in and lazy: the token is created the first time the owner
    asks for a link, not at upload time, so an unshared video never carries
    one. Asking again returns the same token — the link is stable. A collision
    on the unique index (astronomically unlikely, but free to handle) retries
    with a fresh token.
    """
    video = await get_video(db, owner_id, video_id)
    if video.share_token:
        return video.share_token

    for _ in range(3):
        token = secrets.token_urlsafe(32)
        video.share_token = token
        try:
            await db.commit()
            await db.refresh(video)
            logger.info("Video shared: %s", video_id)
            return token
        except IntegrityError:
            await db.rollback()
    raise VideoError("could not mint a unique share token")


async def unshare_video(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    video_id: uuid.UUID,
) -> None:
    """Revoke a video's share link by clearing its token.

    Every outstanding link dies at once — the public routes look the video up
    by token, and a cleared token matches nothing.
    """
    video = await get_video(db, owner_id, video_id)
    if video.share_token is None:
        return
    video.share_token = None
    await db.commit()
    await db.refresh(video)
    logger.info("Video unshared: %s", video_id)


async def get_shared_video(db: AsyncSession, token: str) -> Video:
    """A video by its share token — the one public lookup in the library.

    Raises `VideoNotFound` for an unknown or revoked token (same 404 either
    way, so a revoked link is indistinguishable from one that never existed).
    """
    result = await db.execute(select(Video).where(Video.share_token == token))
    video = result.scalar_one_or_none()
    if video is None:
        raise VideoNotFound(token)
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


async def _can_edit(db: AsyncSession, user_id: uuid.UUID, video: Video) -> bool:
    """Whether `user_id` may mutate this video.

    The uploader always can. For a workspace video, members with an editor
    role (owner/admin/member) can; viewers are read-only.
    """
    if video.owner_id == user_id:
        return True
    if video.workspace_id is None:
        return False
    role = await workspaces_service.member_role(db, video.workspace_id, user_id)
    return workspaces_service.can_edit_videos(role)


class VideoForbidden(VideoError):
    """The video exists but the caller's role can't mutate it (403)."""


async def move_video(
    db: AsyncSession,
    user_id: uuid.UUID,
    video_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None,
) -> Video:
    """Move a video between workspaces (or back to the uploader's library).

    The caller must be able to edit the video in its current home, and must
    be an editor of the destination workspace when it's non-null. Moving to
    a workspace the caller can't edit, or isn't a member of, raises
    `VideoNotFound` — a leaked id never confirms a workspace's existence.
    """
    video = await get_video(db, user_id, video_id)
    if not await _can_edit(db, user_id, video):
        raise VideoForbidden(video_id)
    if workspace_id is not None:
        role = await workspaces_service.member_role(db, workspace_id, user_id)
        if not workspaces_service.can_edit_videos(role):
            raise VideoNotFound(video_id)
    video.workspace_id = workspace_id
    await db.commit()
    await db.refresh(video)
    logger.info("Video %s moved to workspace %s", video_id, workspace_id)
    return video


async def delete_video(db: AsyncSession, owner_id: uuid.UUID, video_id: uuid.UUID) -> None:
    """Remove the row (cascades to frames and transcript segments) and its object.

    The uploader, or an editor-role workspace member, may delete. A viewer
    gets `VideoForbidden` (403) rather than a 404 — they can see the video,
    they just can't delete it.
    """
    video = await get_video(db, owner_id, video_id)
    if not await _can_edit(db, owner_id, video):
        raise VideoForbidden(video_id)
    await db.delete(video)
    await db.commit()
    await run_in_threadpool(storage.delete, video.storage_key)
    logger.info("Video deleted: %s", video_id)
