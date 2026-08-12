"""Video routes: upload, list, status, stream, delete.

Upload is the entry point of the indexing pipeline: it stores the file, opens
a `processing` video row, and enqueues the background job that extracts and
embeds frames.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.auth.deps import CurrentUser, DbSession
from app.auth.schemas import MessageResponse
from app.core.config import get_settings
from app.videos import pipeline
from app.videos import service as videos_service
from app.videos.schemas import StreamUrlOut, VideoListOut, VideoOut
from app.videos.storage import storage
from app.videos.streaming import build_stream_url

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
            detail="File exceeds the 512 MiB upload limit",
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
