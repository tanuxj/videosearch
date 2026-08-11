"""Semantic clip search: prompt → CLIP text vector → pgvector similarity.

Contract (matches the frontend's ``searchClips`` in ``src/lib/api.ts``):

    POST /api/v1/search/clips
    { "video_id": "<uuid>", "prompt": "a red car on a highway", "limit": 9 }
    → { "query": "...", "count": 3, "items": [
         { "id": "...", "start": 3.2, "end": 9.2, "timestamp": 5.0, "score": 0.81 }
       ] }

`timestamp` is the matching frame's second; `start`/`end` give a playback
window around it. `score` is the cosine similarity (0–1) between the prompt
and the frame embedding.
"""

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentUser, DbSession
from app.videos import embedder
from app.videos import service as videos_service
from app.videos.models import Frame

router = APIRouter(prefix="/search", tags=["search"])

# Seconds of playback to show either side of the matching frame.
_CLIP_PAD = 1.8


class ClipSearchRequest(BaseModel):
    video_id: uuid.UUID
    prompt: str = Field(min_length=1, max_length=300, examples=["a red car on a highway"])
    limit: int = Field(default=9, ge=1, le=50)


class ClipItem(BaseModel):
    id: str
    start: float
    end: float
    timestamp: float
    score: float


class ClipSearchResponse(BaseModel):
    query: str
    count: int
    items: list[ClipItem]


@router.post(
    "/clips",
    response_model=ClipSearchResponse,
    summary="Find matching moments in a video",
    description=(
        "Embeds the prompt with CLIP and returns the frames whose visual "
        "content is closest to it, with timestamps and similarity scores."
    ),
    responses={
        404: {"description": "Video not found"},
        409: {"description": "Video is still being indexed"},
    },
)
async def search_clips(
    user: CurrentUser,
    db: DbSession,
    payload: ClipSearchRequest,
) -> ClipSearchResponse:
    try:
        video = await videos_service.get_video(db, user.id, payload.video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc

    if video.status != "ready":
        raise HTTPException(
            status_code=409,
            detail="Video is still being indexed",
        )

    # The text embedding is a ~600 MB model on CPU — never block the loop.
    query_vector = await run_in_threadpool(embedder.embed_text, payload.prompt)

    # `cosine_distance` (the `<=>` operator) is typed through the Vector
    # column, so asyncpg binds the Python list correctly without a raw codec.
    distance = Frame.embedding.cosine_distance(query_vector)
    result = await db.execute(
        select(Frame.id, Frame.timestamp_sec, (1 - distance).label("score"))
        .where(Frame.video_id == payload.video_id)
        .order_by(distance)
        .limit(payload.limit)
    )

    rows = result.all()
    items = [
        ClipItem(
            id=str(row.id),
            start=max(0.0, row.timestamp_sec - _CLIP_PAD),
            end=row.timestamp_sec + _CLIP_PAD,
            timestamp=row.timestamp_sec,
            score=round(float(row.score), 4),
        )
        for row in rows
    ]
    return ClipSearchResponse(query=payload.prompt, count=len(items), items=items)
