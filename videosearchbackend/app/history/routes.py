"""Search-history routes: record and revisit past searches.

``POST /history`` stores what a search returned — prompt, video, and the clips
the user saw — so the History page can list past searches, replay their clips,
and re-run them. Every row is scoped to the signed-in user, and deleting a
video cascades to its history (a record with no video left is unplayable).
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.auth.deps import CurrentUser, DbSession
from app.auth.schemas import MessageResponse
from app.history import service as history_service
from app.history.schemas import SearchHistoryIn, SearchHistoryListOut, SearchHistoryOut
from app.videos import service as videos_service

router = APIRouter(prefix="/history", tags=["history"])


@router.get(
    "",
    response_model=SearchHistoryListOut,
    summary="List my search history",
    description="Searches the signed-in user has run, newest first.",
)
async def list_history(user: CurrentUser, db: DbSession) -> SearchHistoryListOut:
    items = await history_service.list_history(db, user.id)
    return SearchHistoryListOut(items=items, count=len(items))


@router.post(
    "",
    response_model=SearchHistoryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a search",
    description=(
        "Remembers a search the user just ran: the prompt, the video it was "
        "run against, and the clips that came back. The video must belong to "
        "the user."
    ),
    responses={404: {"description": "Video not found"}},
)
async def create_history(
    user: CurrentUser,
    db: DbSession,
    payload: SearchHistoryIn,
) -> SearchHistoryOut:
    # The video must exist and belong to the user — never record a search
    # against someone else's (or a deleted) video.
    try:
        await videos_service.get_video(db, user.id, payload.video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc

    record = await history_service.create_history(
        db,
        owner_id=user.id,
        video_id=payload.video_id,
        prompt=payload.prompt,
        clips=[clip.model_dump() for clip in payload.clips],
        expanded=payload.expanded,
        min_score=payload.min_score,
    )
    return SearchHistoryOut.model_validate(record)


@router.delete(
    "/{record_id}",
    response_model=MessageResponse,
    summary="Delete one search",
    description="Removes a single search-history record (ownership enforced).",
    responses={404: {"description": "Search not found"}},
)
async def delete_history(
    user: CurrentUser,
    db: DbSession,
    record_id: uuid.UUID,
) -> MessageResponse:
    try:
        await history_service.delete_history(db, user.id, record_id)
    except history_service.SearchHistoryNotFound as exc:
        raise HTTPException(status_code=404, detail="Search not found") from exc
    return MessageResponse(detail="Search deleted")


@router.delete(
    "",
    response_model=MessageResponse,
    summary="Clear all search history",
    description="Removes every search-history record for the signed-in user.",
)
async def clear_history(user: CurrentUser, db: DbSession) -> MessageResponse:
    count = await history_service.clear_history(db, user.id)
    return MessageResponse(detail=f"Cleared {count} searches")
