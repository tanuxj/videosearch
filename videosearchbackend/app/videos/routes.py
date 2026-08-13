"""Video routes: upload, list, status, stream, clip, delete.

Upload is the entry point of the indexing pipeline: it stores the file, opens
a `processing` video row, and enqueues the background job that extracts and
embeds frames.
"""

import math
import shutil
import tempfile
import uuid
from functools import partial
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.auth.deps import CurrentUser, DbSession
from app.auth.schemas import MessageResponse
from app.core.config import get_settings
from app.videos import clips, pipeline
from app.videos import service as videos_service
from app.videos.schemas import (
    CompleteMultipartIn,
    CompleteUploadOut,
    MultipartPartOut,
    PresignMultipartOut,
    PresignUploadIn,
    PresignUploadOut,
    StreamUrlOut,
    VideoListOut,
    VideoOut,
)
from app.videos.storage import storage
from app.videos.streaming import build_stream_url

# Longest extractable clip (seconds). Keeps ffmpeg runs (and downloads) sane.
MAX_CLIP_SECONDS = 600.0

# S3/R2 floor for a non-last multipart chunk — smaller parts are rejected on
# completion. The browser uploads chunks this size (or larger) to the
# presigned per-part URLs.
MIN_MULTIPART_PART_BYTES = 5 * 1024 * 1024
# R2 supports up to 10_000 parts; we stay well under so the same flow works
# against plain S3 too.
MAX_MULTIPART_PARTS = 1000


def _human_bytes(n: int) -> str:
    """Compact size for error messages: 10 GiB, 512 MiB, …"""
    value = n / (1024**3)
    if value >= 1:
        return f"{value:g} GiB"
    return f"{n / (1024**2):g} MiB"


def _too_large_detail() -> str:
    return f"File exceeds the {_human_bytes(videos_service.MAX_UPLOAD_BYTES)} upload limit"


def _plan_parts(size_bytes: int) -> tuple[int, int]:
    """Pick `(part_size, part_count)` so chunks are S3-valid and few in number.

    Each non-final chunk is at least 5 MiB (S3's floor) and there are at most
    `MAX_MULTIPART_PARTS` chunks total. A 10 GiB file ends up with ~1000 parts
    of ~10.7 MiB; a 1 GiB file with 205 parts of 5 MiB.
    """
    part_size = max(MIN_MULTIPART_PART_BYTES, math.ceil(size_bytes / MAX_MULTIPART_PARTS))
    part_count = max(1, math.ceil(size_bytes / part_size))
    return part_size, part_count


def _cleanup_clip_files(source: str | None, temp_dir: Path) -> None:
    """Remove the clip output dir, and the source only when we created it.

    `source` is a temp download we own and must delete. It is None whenever the
    source was a presigned URL (nothing local) or the live stored file on the
    local backend (must be kept). The `temp_dir` always holds our clip output
    and is always ours to delete.
    """
    if source is not None:
        Path(source).unlink(missing_ok=True)
    shutil.rmtree(temp_dir, ignore_errors=True)


settings = get_settings()

router = APIRouter(prefix="/videos", tags=["videos"])

_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".m4v": "video/x-m4v",
}


@router.post(
    "",
    response_model=VideoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a video",
    description=(
        "Stores the file in object storage, opens a `processing` video row "
        "and starts the indexing pipeline in the background."
    ),
    responses={
        415: {"description": "Unsupported file type"},
        413: {"description": "File too large"},
    },
)
async def upload_video(
    user: CurrentUser,
    db: DbSession,
    background_tasks: BackgroundTasks,
    file: Annotated[
        UploadFile,
        File(description="The video file (mp4, mov, webm, mkv, avi, m4v)"),
    ],
) -> VideoOut:
    filename = file.filename or "video.mp4"
    try:
        video, staged_path = await videos_service.create_video(
            db,
            owner_id=user.id,
            filename=filename,
            size_bytes=file.size or 0,
            content_type=file.content_type,
            file=file.file,
        )
    except videos_service.UnsupportedFileType as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {exc.args[0] or 'unknown'}. "
            "Allowed: mp4, mov, webm, mkv, avi, m4v",
        ) from exc
    except videos_service.FileTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=_too_large_detail(),
        ) from exc

    # Fire-and-forget: the response goes out immediately with status
    # `processing`, and indexing runs to completion in the background. The
    # pipeline takes ownership of `staged_path` and deletes it when done.
    if settings.index_on_upload:
        background_tasks.add_task(pipeline.index_video, video.id, staged_path)
    elif staged_path is not None:
        # Nothing will consume it, so don't leave it in the temp dir.
        staged_path.unlink(missing_ok=True)
    return VideoOut.model_validate(video)


@router.post(
    "/presign",
    response_model=PresignUploadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve a video and get a direct-upload URL",
    description=(
        "Creates a `processing` video row and returns a short-lived presigned "
        "PUT URL so the browser uploads the file straight to R2 — large files "
        "never buffer in the API. When object storage is local disk, "
        "`upload_url` is null and clients must fall back to the multipart "
        "upload endpoint. Finish with `POST /videos/{id}/complete`."
    ),
    responses={
        415: {"description": "Unsupported file type"},
        413: {"description": "File too large"},
    },
)
async def presign_upload(
    user: CurrentUser,
    db: DbSession,
    payload: PresignUploadIn,
) -> PresignUploadOut:
    # Validate metadata first so a bad request fails before any row is
    # created or storage is consulted.
    try:
        videos_service.validate_upload(payload.filename, payload.size_bytes)
    except videos_service.UnsupportedFileType as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {exc.args[0] or 'unknown'}. "
            "Allowed: mp4, mov, webm, mkv, avi, m4v",
        ) from exc
    except videos_service.FileTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=_too_large_detail(),
        ) from exc

    if not storage.presign_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Direct uploads are unavailable — use the multipart upload endpoint.",
        )

    video = await videos_service.create_pending_video(
        db,
        owner_id=user.id,
        filename=payload.filename,
        size_bytes=payload.size_bytes,
    )

    upload_url = await run_in_threadpool(
        storage.presign_put,
        video.storage_key,
        payload.content_type,
        settings.presign_url_ttl_seconds,
    )
    return PresignUploadOut(
        video=VideoOut.model_validate(video),
        upload_url=upload_url,
        expires_in=settings.presign_url_ttl_seconds,
    )


@router.post(
    "/presign/multipart",
    response_model=PresignMultipartOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve a video for a multipart upload",
    description=(
        "For files above the 5 GiB single-PUT cap. Creates a `processing` "
        "video row, opens an S3/R2 multipart upload and returns a presigned "
        "PUT URL per chunk. The browser uploads each chunk straight to "
        "storage, then calls `POST /videos/{id}/complete/multipart` with the "
        "chunks' ETags. When object storage is local disk, returns 409 and "
        "clients fall back to the multipart upload endpoint."
    ),
    responses={
        415: {"description": "Unsupported file type"},
        413: {"description": "File too large"},
        409: {"description": "Direct uploads unavailable"},
    },
)
async def presign_multipart_upload(
    user: CurrentUser,
    db: DbSession,
    payload: PresignUploadIn,
) -> PresignMultipartOut:
    try:
        videos_service.validate_upload(payload.filename, payload.size_bytes)
    except videos_service.UnsupportedFileType as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {exc.args[0] or 'unknown'}. "
            "Allowed: mp4, mov, webm, mkv, avi, m4v",
        ) from exc
    except videos_service.FileTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=_too_large_detail(),
        ) from exc

    if not storage.presign_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Direct uploads are unavailable — use the multipart upload endpoint.",
        )

    video = await videos_service.create_pending_video(
        db,
        owner_id=user.id,
        filename=payload.filename,
        size_bytes=payload.size_bytes,
    )

    # Open the multipart upload and mint one URL per chunk. Any failure here
    # must not leave a reserved row (or a dangling multipart upload) behind.
    upload_id: str | None = None
    try:
        upload_id = await run_in_threadpool(
            storage.create_multipart_upload,
            video.storage_key,
            payload.content_type,
        )
        if upload_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Multipart uploads are unavailable on this storage backend.",
            )

        part_size, part_count = _plan_parts(payload.size_bytes)
        parts: list[MultipartPartOut] = []
        for number in range(1, part_count + 1):
            part_url = await run_in_threadpool(
                storage.presign_part,
                video.storage_key,
                upload_id,
                number,
                settings.presign_url_ttl_seconds,
            )
            parts.append(MultipartPartOut(part_number=number, url=part_url))

        return PresignMultipartOut(
            video=VideoOut.model_validate(video),
            upload_id=upload_id,
            part_size=part_size,
            parts=parts,
            expires_in=settings.presign_url_ttl_seconds,
        )
    except Exception:
        if upload_id is not None:
            await run_in_threadpool(storage.abort_multipart, video.storage_key, upload_id)
        await videos_service.delete_video(db, user.id, video.id)
        raise


@router.post(
    "/{video_id}/complete",
    response_model=CompleteUploadOut,
    summary="Confirm a direct upload and start indexing",
    description=(
        "Called after the browser PUTs the file to the presigned URL. Verifies "
        "the object actually landed (and matches the declared size) before "
        "starting the indexing pipeline."
    ),
    responses={404: {"description": "Video not found"}},
)
async def complete_upload(
    user: CurrentUser,
    db: DbSession,
    background_tasks: BackgroundTasks,
    video_id: uuid.UUID,
) -> CompleteUploadOut:
    try:
        video = await videos_service.get_video(db, user.id, video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc

    # Confirm the bytes actually landed — a client that mints a URL but never
    # PUTs the file (or uploads a different size) fails fast here.
    try:
        await videos_service.complete_pending_video(
            db,
            owner_id=user.id,
            video_id=video_id,
            expected_bytes=video.size_bytes,
        )
    except videos_service.UploadNotComplete as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="File has not been uploaded yet — PUT it to the presigned URL first.",
        ) from exc
    except videos_service.UploadSizeMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Uploaded size ({exc.actual} bytes) does not match the declared "
            f"size ({exc.expected} bytes). Upload the file again.",
        ) from exc

    # The object is confirmed on disk/R2 — indexing can begin. No staged path
    # is handed over (the API never buffered the bytes), so the pipeline
    # pulls the file from storage itself. Only schedule while the row is
    # still `processing`: a replayed complete (double-click, retry) must not
    # enqueue two pipelines for the same video — the second would hit the
    # per-video-per-second unique constraint and mark the video failed.
    if settings.index_on_upload and video.status == "processing":
        background_tasks.add_task(pipeline.index_video, video.id)
    if video.status == "processing":
        message = "Upload confirmed — indexing started"
    else:
        message = "Upload confirmed"
    return CompleteUploadOut(video=VideoOut.model_validate(video), message=message)


@router.post(
    "/{video_id}/complete/multipart",
    response_model=CompleteUploadOut,
    summary="Assemble a multipart upload and start indexing",
    description=(
        "Called after the browser PUTs every chunk to the per-part presigned "
        "URLs from `POST /videos/presign/multipart`. Assembles the object and "
        "verifies its size before starting the indexing pipeline."
    ),
    responses={404: {"description": "Video not found"}},
)
async def complete_multipart_video(
    user: CurrentUser,
    db: DbSession,
    background_tasks: BackgroundTasks,
    video_id: uuid.UUID,
    payload: CompleteMultipartIn,
) -> CompleteUploadOut:
    try:
        video = await videos_service.get_video(db, user.id, video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc

    try:
        await run_in_threadpool(
            storage.complete_multipart,
            video.storage_key,
            payload.upload_id,
            [(part.part_number, part.etag) for part in payload.parts],
        )
    except Exception as exc:
        # InvalidPart / NoSuchUpload / missing chunks — the object isn't whole,
        # so surface it as a client error rather than a 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Could not assemble the uploaded parts: {exc}",
        ) from exc

    # Confirm the assembled object matches the declared size before indexing.
    try:
        await videos_service.complete_pending_video(
            db,
            owner_id=user.id,
            video_id=video_id,
            expected_bytes=video.size_bytes,
        )
    except videos_service.UploadNotComplete as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="File has not been uploaded yet — PUT the parts first.",
        ) from exc
    except videos_service.UploadSizeMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Uploaded size ({exc.actual} bytes) does not match the declared "
            f"size ({exc.expected} bytes). Upload the file again.",
        ) from exc

    if settings.index_on_upload and video.status == "processing":
        background_tasks.add_task(pipeline.index_video, video.id)
    if video.status == "processing":
        message = "Upload confirmed — indexing started"
    else:
        message = "Upload confirmed"
    return CompleteUploadOut(video=VideoOut.model_validate(video), message=message)


@router.get(
    "",
    response_model=VideoListOut,
    summary="List my videos",
    description="Videos owned by the signed-in user, newest first.",
)
async def list_videos(user: CurrentUser, db: DbSession) -> VideoListOut:
    items = await videos_service.list_videos(db, user.id)
    return VideoListOut(items=items, count=len(items))


@router.get(
    "/{video_id}",
    response_model=VideoOut,
    summary="Video status and metadata",
    responses={404: {"description": "Video not found"}},
)
async def get_video(user: CurrentUser, db: DbSession, video_id: uuid.UUID) -> VideoOut:
    try:
        video = await videos_service.get_video(db, user.id, video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc
    return VideoOut.model_validate(video)


@router.get(
    "/{video_id}/stream-url",
    response_model=StreamUrlOut,
    summary="Get a playback URL for a video",
    description=(
        "Returns a short-lived signed URL served by the edge streaming Worker "
        "when configured; otherwise falls back to the API-proxied stream path. "
        "The frontend uses this to play videos without the API proxying bytes."
    ),
    responses={404: {"description": "Video not found"}},
)
async def stream_url(user: CurrentUser, db: DbSession, video_id: uuid.UUID) -> StreamUrlOut:
    try:
        video = await videos_service.get_video(db, user.id, video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc

    signed = build_stream_url(video.storage_key)
    if signed is not None:
        return StreamUrlOut(url=signed, worker=True)
    return StreamUrlOut(
        url=f"{settings.api_v1_prefix}/videos/{video_id}/stream",
        worker=False,
    )


@router.get(
    "/{video_id}/stream",
    response_class=StreamingResponse,
    response_model=None,
    summary="Stream the video (Range-aware)",
    description=(
        "Returns the stored file with byte-range support so the browser's "
        "<video> element can seek. Local backend uses FileResponse; R2 is "
        "proxied through the API."
    ),
    responses={404: {"description": "Video not found"}},
)
async def stream_video(
    user: CurrentUser,
    db: DbSession,
    request: Request,
    video_id: uuid.UUID,
):
    try:
        video = await videos_service.get_video(db, user.id, video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc

    ext = f".{video.storage_key.rsplit('.', 1)[-1].lower()}"
    media_type = _MEDIA_TYPES.get(ext)
    return storage.stream_response(video.storage_key, media_type, request.headers.get("range"))


@router.get(
    "/{video_id}/clip",
    response_class=FileResponse,
    response_model=None,
    summary="Download a trimmed clip",
    description=(
        "Cuts the video to the [start, end) second range with ffmpeg and "
        "returns it as an MP4 attachment. Clips are capped at 10 minutes "
        "and validated against the video's known duration when available."
    ),
    responses={
        404: {"description": "Video not found"},
        422: {"description": "Invalid clip range"},
        503: {"description": "Clip extraction unavailable"},
    },
)
async def download_clip(
    user: CurrentUser,
    db: DbSession,
    video_id: uuid.UUID,
    start: float = Query(ge=0, description="Clip start, in seconds"),
    end: float = Query(gt=0, description="Clip end, in seconds"),
):
    try:
        video = await videos_service.get_video(db, user.id, video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc

    if not (math.isfinite(start) and math.isfinite(end)):
        raise HTTPException(status_code=422, detail="Clip times must be finite numbers")
    if end <= start:
        raise HTTPException(status_code=422, detail="Clip end must be after start")
    # Clamp to the known duration first — a stale result can't request past
    # EOF, and a long request on a short video is the user's clip, not an
    # over-limit one.
    if video.duration_seconds is not None and end > video.duration_seconds:
        end = video.duration_seconds
        if end <= start:
            raise HTTPException(status_code=422, detail="Clip lies beyond the video's end")
    if end - start > MAX_CLIP_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=f"Clip is longer than the {MAX_CLIP_SECONDS:.0f}s limit",
        )

    # ffmpeg reads the source itself. On R2 that is a presigned URL, so it
    # range-requests only the bytes around the cut instead of downloading the
    # whole object — the difference between seconds and minutes on a large file.
    # A statically linked ffmpeg segfaults on URL input, so only offer one when
    # the resolved binary can actually open a network source.
    ffmpeg_source, owns_source = await run_in_threadpool(
        partial(
            storage.ffmpeg_source,
            video.storage_key,
            settings.presign_url_ttl_seconds,
            allow_url=clips.supports_network_input(),
        )
    )
    # Only a temp download is ours to delete; a URL or the live local file is not.
    source: str | None = ffmpeg_source if owns_source else None
    temp_dir = Path(tempfile.mkdtemp(prefix="videosearch-clip-"))
    output = temp_dir / f"clip-{video_id}.mp4"
    try:
        try:
            await run_in_threadpool(clips.trim, ffmpeg_source, start, end, output)
        except clips.ClipError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Could not extract clip: {exc}",
            ) from exc

        name = Path(video.name).stem[:80] or "clip"
        filename = f"{name} [{int(start)}-{int(end)}s].mp4"
        return FileResponse(
            output,
            media_type="video/mp4",
            filename=filename,
            content_disposition_type="attachment",
            # Files must survive until Starlette finishes streaming the body, so
            # they are removed on a background task — never in this coroutine.
            background=BackgroundTask(_cleanup_clip_files, source, temp_dir),
        )
    except Exception:
        # Any failure before the response streams (unexpected errors too — a
        # missing imageio-ffmpeg, an OSError) must not leak the temp files.
        _cleanup_clip_files(source, temp_dir)
        raise


@router.delete(
    "/{video_id}",
    response_model=MessageResponse,
    summary="Delete a video",
    description="Removes the video row (cascading to its frame index) and the stored file.",
    responses={404: {"description": "Video not found"}},
)
async def delete_video(user: CurrentUser, db: DbSession, video_id: uuid.UUID) -> MessageResponse:
    try:
        await videos_service.delete_video(db, user.id, video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc
    return MessageResponse(detail="Video deleted")
