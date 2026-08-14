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
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.videos import embedder, query_expand, twelvelabs
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
    # Which index answers. `clip` is the local pgvector one (visual only);
    # `twelvelabs` is the managed Marengo index, which also searches audio and
    # so can answer questions about what was *said*, which CLIP structurally
    # cannot. Both return the same shape, so the client renders them alike.
    engine: Literal["clip", "twelvelabs"] = "clip"


class ClipItem(BaseModel):
    id: str
    start: float
    end: float
    timestamp: float
    score: float
    # The speech inside the matched moment, when the engine reports it.
    # Marengo does; CLIP has no audio and always leaves this None.
    text: str | None = None


class ClipSearchResponse(BaseModel):
    query: str
    count: int
    min_score: float
    expanded: bool
    items: list[ClipItem]
    # Which index actually answered. Echoed back because the client offers a
    # choice, and a mismatch (asked for one, got the other) would otherwise be
    # invisible in the results.
    engine: str = "clip"


@dataclass
class ClipSearchResult:
    """What a search found: ranked scenes plus the threshold that filtered them."""

    items: list[ClipItem]
    min_score: float
    expanded: bool


async def run_clip_search(
    db: AsyncSession,
    video_id: uuid.UUID,
    prompt: str,
    *,
    limit: int,
    duration_seconds: float | None,
) -> ClipSearchResult:
    """Embed `prompt` (plus LLM-expanded variants) and rank the video's scenes.

    Shared by the search route and the URL-import auto-extract job so both
    rank identically: per-frame best similarity across query variants, scenes
    merged within ``search_merge_window_seconds``, only frames above
    ``search_min_similarity`` kept, results best-first and capped at `limit`.
    `duration_seconds` clamps clip end times to the video's real length.
    """
    # The "middleman": rewrite a terse/broken prompt into visual descriptions
    # CLIP can actually match. Runs on a worker thread — an LLM round trip is
    # network I/O, and the CLIP model is CPU-bound, so neither blocks the loop.
    variants = await run_in_threadpool(query_expand.expand_prompt, prompt)
    expanded = variants != [prompt]

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
                Frame.video_id == video_id
            )
        )
        for row in result.all():
            score = float(row.score)
            current = best.get(row.id)
            if current is None or score > current[1]:
                best[row.id] = (row.timestamp_sec, score, str(row.id))

    frames = sorted(best.values(), key=lambda frame: frame[0])
    scenes = _merge_scenes(frames, min_score, merge_window)

    items = []
    for scene in scenes:
        first_ts = scene[0][0]
        last_ts = scene[-1][0]
        best_ts, best_score, best_id = max(scene, key=lambda frame: frame[1])
        end = last_ts + _CLIP_PAD
        if duration_seconds:
            end = min(end, duration_seconds)
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
    return ClipSearchResult(items=items[:limit], min_score=min_score, expanded=expanded)


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

    if payload.engine == "twelvelabs":
        items = await _remote_search(video, payload.prompt, payload.limit)
        return ClipSearchResponse(
            query=payload.prompt,
            count=len(items),
            # Marengo applies its own relevance cut, so there is no local
            # threshold to report — 0 means "nothing was filtered here".
            min_score=0.0,
            expanded=False,
            items=items,
            engine="twelvelabs",
        )

    # The local index is only complete once every frame is embedded; the
    # remote one has no such dependency, which is why this check sits here
    # rather than above the engine switch.
    if video.status != "ready":
        raise HTTPException(
            status_code=409,
            detail="Video is still being indexed",
        )

    result = await run_clip_search(
        db,
        payload.video_id,
        payload.prompt,
        limit=payload.limit,
        duration_seconds=video.duration_seconds,
    )
    return ClipSearchResponse(
        query=payload.prompt,
        count=len(result.items),
        min_score=round(result.min_score, 4),
        expanded=result.expanded,
        items=result.items,
        engine="clip",
    )


async def _remote_search(video, prompt: str, limit: int) -> list[ClipItem]:
    """Search the Twelve Labs index and return results in this app's shape.

    Their search spans the whole index, so hits are filtered down to the one
    video being asked about — matching on the provider's own video id, which
    is what search results are keyed by.
    """
    if not settings.twelvelabs_configured:
        raise HTTPException(
            status_code=409,
            detail="Remote search is not configured on this server (set TWELVELABS_API_KEY).",
        )
    if video.remote_index_status != "ready" or not video.remote_video_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "This video has not been indexed remotely yet — "
                "run POST /videos/{id}/remote-index first."
            ),
        )

    try:
        index_id = await run_in_threadpool(twelvelabs.ensure_index)
        # Over-fetch: hits span every video in the index, so the slice for
        # this one can be a fraction of the page.
        hits = await run_in_threadpool(
            twelvelabs.search, index_id, prompt, max(limit * 4, 20)
        )
    except twelvelabs.TwelveLabsError as exc:
        raise HTTPException(status_code=502, detail=f"Remote search failed: {exc}") from exc

    items: list[ClipItem] = []
    for index, hit in enumerate(hits):
        if hit.video_id != video.remote_video_id:
            continue
        end = hit.end
        if video.duration_seconds:
            end = min(end, video.duration_seconds)
        items.append(
            ClipItem(
                id=f"tl-{index}-{round(hit.start * 100)}",
                start=round(max(0.0, hit.start), 2),
                end=round(end, 2),
                # No single "best frame" in a video-native model — the middle
                # of the moment is the honest thumbnail point.
                timestamp=round((hit.start + end) / 2, 2),
                # Marengo ranks rather than scoring; this is a stand-in that
                # preserves the ordering for the UI's relative bars.
                score=twelvelabs.rank_score(hit.rank),
                text=hit.transcription,
            )
        )
        if len(items) >= limit:
            break
    return items
