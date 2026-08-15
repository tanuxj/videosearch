"""Public share routes: the unauthenticated side of share links.

Everything in here is keyed by a video's `share_token` — the unguessable link
the owner minted with `GET /videos/{id}/share` — and deliberately carries no
`CurrentUser` dependency, so a recipient with the link can watch the video and
read its transcript without an account.

Four endpoints, mirroring the authenticated video routes they stand in for:

* ``GET /shares/{token}`` — the video's public metadata plus its stream path.
* ``GET /shares/{token}/stream`` — Range-aware playback (local backend uses
  FileResponse; R2 is proxied exactly like the authenticated stream).
* ``GET /shares/{token}/transcript`` — timed text, same shape as the
  authenticated endpoint.
* ``GET /shares/{token}/captions.vtt`` — WebVTT for a `<track>` element, which
  can point straight at this URL because it needs no auth header.

An unknown or revoked token is a 404 everywhere — a dead link looks the same
whether it never existed or was unshared.
"""

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.auth.deps import DbSession
from app.core.config import get_settings
from app.videos import service as videos_service
from app.videos import transcribe
from app.videos.schemas import (
    PublicShareOut,
    TranscriptOut,
    TranscriptSegmentOut,
)

router = APIRouter(prefix="/shares", tags=["shares"])

settings = get_settings()


def _share_url(token: str) -> str:
    """The app-relative public stream path for a shared video."""
    return f"{settings.api_v1_prefix}/shares/{token}/stream"


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="This video isn't shared — the link may have been revoked.",
    )


@router.get(
    "/{token}",
    response_model=PublicShareOut,
    summary="Public metadata for a shared video",
    description=(
        "Look a video up by its share token. Returns only what a public page "
        "may know — no owner, no storage internals — plus the public stream "
        "path the player should use."
    ),
    responses={404: {"description": "Unknown or revoked share token"}},
)
async def get_public_share(db: DbSession, token: str) -> PublicShareOut:
    try:
        video = await videos_service.get_shared_video(db, token)
    except videos_service.VideoNotFound as exc:
        raise _not_found() from exc
    return PublicShareOut(
        id=video.id,
        name=video.name,
        duration_seconds=video.duration_seconds,
        status=video.status,
        source=video.source,
        has_video=video.has_video,
        transcript_status=video.transcript_status,
        language=video.language,
        created_at=video.created_at,
        stream_url=_share_url(token),
    )


@router.get(
    "/{token}/stream",
    response_class=StreamingResponse,
    response_model=None,
    summary="Stream a shared video (Range-aware, no auth)",
    description=(
        "Serves the stored file to anyone holding the share token, with the "
        "same byte-range support as the authenticated stream so the browser's "
        "<video> element can seek."
    ),
    responses={404: {"description": "Unknown or revoked share token"}},
)
async def stream_shared_video(
    db: DbSession,
    request: Request,
    token: str,
):
    try:
        video = await videos_service.get_shared_video(db, token)
    except videos_service.VideoNotFound as exc:
        raise _not_found() from exc

    ext = f".{video.storage_key.rsplit('.', 1)[-1].lower()}"
    media_type = videos_service.MEDIA_TYPES.get(ext)
    return videos_service.storage.stream_response(
        video.storage_key,
        media_type,
        request.headers.get("range"),
    )


@router.get(
    "/{token}/transcript",
    response_model=TranscriptOut,
    summary="A shared video's transcript (no auth)",
    description=(
        "The same timed-text payload as the authenticated transcript route, "
        "keyed by share token so the public page can render it."
    ),
    responses={404: {"description": "Unknown or revoked share token"}},
)
async def get_public_transcript(db: DbSession, token: str) -> TranscriptOut:
    try:
        video = await videos_service.get_shared_video(db, token)
    except videos_service.VideoNotFound as exc:
        raise _not_found() from exc

    segments = await videos_service.list_transcript_segments(db, video.id)
    return TranscriptOut(
        status=video.transcript_status,
        language=video.language,
        error=video.transcript_error,
        segments=[
            TranscriptSegmentOut(start=item.start_sec, end=item.end_sec, text=item.text)
            for item in segments
        ],
        count=len(segments),
    )


@router.get(
    "/{token}/captions.vtt",
    response_class=PlainTextResponse,
    response_model=None,
    summary="A shared video's subtitles as WebVTT (no auth)",
    description=(
        "WebVTT for a `<track>` element on the public page. Public, so the "
        "browser can load it directly — no Authorization header needed."
    ),
    responses={404: {"description": "Unknown or revoked share token"}},
)
async def get_public_captions(db: DbSession, token: str) -> PlainTextResponse:
    try:
        video = await videos_service.get_shared_video(db, token)
    except videos_service.VideoNotFound as exc:
        raise _not_found() from exc

    segments = await videos_service.list_transcript_segments(db, video.id)
    body = transcribe.to_vtt(
        [
            transcribe.Segment(start=item.start_sec, end=item.end_sec, text=item.text)
            for item in segments
        ]
    )
    return PlainTextResponse(body, media_type="text/vtt; charset=utf-8")
