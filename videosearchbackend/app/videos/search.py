"""Semantic clip search: prompt → CLIP text vectors → pgvector similarity.

Contract (matches the frontend's ``searchClips`` in ``src/lib/api.ts``):

    POST /api/v1/search/clips
    { "video_id": "<uuid>", "prompt": "car red road", "limit": 9 }
    → { "query": "...", "count": 1, "min_score": 0.24, "expanded": true, "items": [
         { "id": "...", "start": 3.2, "end": 9.2, "timestamp": 5.0, "score": 0.81 }
       ] }

Search-quality guarantees (what makes this not "the least-bad random frame"):

* **Real matches only.** Frames whose similarity falls below
  ``search_min_similarity`` are excluded. Unrelated CLIP text↔image pairs
  cluster around ~0.2 similarity, so a prompt that describes nothing in the
  video returns ``count: 0`` — never a ranked list of its most dissimilar-to-
  least-dissimilar frames.
* **Query expansion (the "middleman").** When an LLM is configured, the raw
  prompt is rewritten into a few visually-grounded variants (see
  ``query_expand.py``) and every variant is embedded; each frame keeps its
  best score across variants. Broken-English or terse prompts therefore still
  land if any variant names what the shot actually shows. ``expanded`` reports
  whether variants were used.
* **Scenes, not frames.** Matching frames closer than
  ``search_merge_window_seconds`` apart are merged into a single scene, so a
  multi-second moment is returned once with a ``start``/``end`` that span the
  whole moment instead of several overlapping ±1.8s single-frame windows.
* ``timestamp`` is the strongest frame inside the scene (used for the
  thumbnail); ``score`` is that frame's raw cosine similarity (0–1).
"""

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.videos import embedder, query_expand
from app.videos import service as videos_service
from app.videos.models import Frame

router = APIRouter(prefix="/search", tags=["search"])

settings = get_settings()

# Seconds of playback to show either side of a scene's first/last matching frame.
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
    min_score: float
    expanded: bool
    items: list[ClipItem]


def _merge_scenes(frames, min_score: float, merge_window: float) -> list[list]:
    """Group above-threshold frames (ordered by timestamp) into scenes.

    ``frames`` is an iterable of ``(timestamp, score, frame_id)`` sorted by
    timestamp. Frames below `min_score` are dropped, and a new scene starts
    whenever the gap to the previous kept frame exceeds `merge_window`, so
    brief dips in similarity inside a continuous moment still read as one
    clip. Each scene is a list of ``(timestamp, score, frame_id)`` tuples.
    """
    scenes: list[list] = []
    current: list = []
    for ts, score, frame_id in frames:
        if score < min_score:
            if current:
                scenes.append(current)
                current = []
            continue
        if current and ts - current[-1][0] > merge_window:
            scenes.append(current)
            current = []
        current.append((ts, score, frame_id))
    if current:
        scenes.append(current)
    return scenes


@router.post(
    "/clips",
    response_model=ClipSearchResponse,
    summary="Find matching moments in a video",
    description=(
        "Embeds the prompt (plus LLM-expanded variants when configured) with "
        "CLIP and returns the scenes (merged runs of matching frames) whose "
        "visual content is close enough, with timestamps and similarity "
        "scores. Returns an empty list when nothing in the video matches."
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

    # The "middleman": rewrite a terse/broken prompt into visual descriptions
    # CLIP can actually match. Runs on a worker thread — an LLM round trip is
    # network I/O, and the CLIP model is CPU-bound, so neither blocks the loop.
    variants = await run_in_threadpool(query_expand.expand_prompt, payload.prompt)
    expanded = variants != [payload.prompt]

    min_score = settings.search_min_similarity
    merge_window = settings.search_merge_window_seconds

    # Per-frame best similarity across all query variants: an expanded variant
    # that names the exact object in a shot should win over the raw prompt.
    # The whole video is scanned (ordered by timestamp later) so the threshold
    # is a true "nothing matched" test and every contiguous run merges into a
    # scene. One video is a few thousand rows at most; the HNSW ANN index
    # would silently drop frames (and with them, whole scenes) under the cap.
    best: dict[uuid.UUID, tuple[float, float, str]] = {}
    for variant in variants:
        # The text embedding is a ~600 MB model on CPU — never block the loop.
        query_vector = await run_in_threadpool(embedder.embed_text, variant)
        distance = Frame.embedding.cosine_distance(query_vector)
        result = await db.execute(
            select(Frame.id, Frame.timestamp_sec, (1 - distance).label("score")).where(
                Frame.video_id == payload.video_id
            )
        )
        for row in result.all():
            score = float(row.score)
            current = best.get(row.id)
            if current is None or score > current[1]:
                best[row.id] = (row.timestamp_sec, score, str(row.id))

    frames = sorted(best.values(), key=lambda frame: frame[0])
    scenes = _merge_scenes(frames, min_score, merge_window)

    duration = video.duration_seconds
    items = []
    for scene in scenes:
        first_ts = scene[0][0]
        last_ts = scene[-1][0]
        best_ts, best_score, best_id = max(scene, key=lambda frame: frame[1])
        end = last_ts + _CLIP_PAD
        if duration:
            end = min(end, duration)
        items.append(
            ClipItem(
                id=best_id,
                start=max(0.0, round(first_ts - _CLIP_PAD, 2)),
                end=round(end, 2),
                timestamp=round(best_ts, 2),
                score=round(best_score, 4),
            )
        )

    items.sort(key=lambda item: item.score, reverse=True)
    items = items[: payload.limit]
    return ClipSearchResponse(
        query=payload.prompt,
        count=len(items),
        min_score=round(min_score, 4),
        expanded=expanded,
        items=items,
    )
