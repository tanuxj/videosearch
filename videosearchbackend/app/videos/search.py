"""Semantic clip search: prompt → CLIP text vectors → pgvector similarity.

Contract (matches the frontend's ``searchClips`` in ``src/lib/api.ts``):

    POST /api/v1/search/clips
    { "video_id": "<uuid>", "prompt": "car red road", "limit": 9 }
    → { "query": "...", "count": 1, "min_score": 0.08, "expanded": true, "items": [
         { "id": "...", "start": 3.2, "end": 9.2, "timestamp": 5.0, "score": 0.81 }
       ] }

Search-quality guarantees (what makes this not "the least-bad random frame"):

* **Real matches only.** Frames whose similarity falls below
  ``search_min_similarity`` are excluded. Unrelated text↔image pairs cluster
  around ~0.2 under CLIP and ~0.02–0.06 under SigLIP 2 (the default is
  resolved per model — see ``DEFAULT_SEARCH_MIN_SIMILARITY``), so a prompt
  that describes nothing in the video returns ``count: 0`` — never a ranked
  list of its most dissimilar-to-least-dissimilar frames.
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

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import DbSession, RequestUserDep
from app.core.config import get_settings
from app.videos import captions, embedder, pipeline, query_expand
from app.videos import service as videos_service
from app.videos.models import Frame
from app.videos.storage import storage

router = APIRouter(prefix="/search", tags=["search"])

settings = get_settings()

# Seconds of playback to show either side of a scene's first/last matching frame.
_CLIP_PAD = 1.8

# Curation: scenes scoring below this fraction of the best scene are dropped.
# The absolute `search_min_similarity` floor stays as-is; this trims the weak
# tail that only cleared it because nothing better existed — the results the
# UI would otherwise show as 30–50% "matches" under a strong top hit.
_RELATIVE_FLOOR = 0.5

# Per-variant caption match, before merging into frame scores. Caption
# text↔text similarity runs far higher than text↔image (well-phrased pairs
# 0.6–0.9, unrelated ~0.3–0.5), so a raw caption cosine would dominate the
# CLIP-score scale it is merged into — a caption that says the thing (cos ~0.7)
# lands near CLIP's real-match band (0.24–0.45) only after discounting.
_CAPTION_WEIGHT = 0.35


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


class GroundRequest(BaseModel):
    """Locate a phrase inside one frame of a video (Florence-2 grounding)."""

    timestamp: float = Field(ge=0, description="Seconds into the video")
    phrase: str = Field(min_length=1, max_length=200, examples=["red car"])


class GroundBox(BaseModel):
    """One bounding box, normalised 0–1 (x1, y1, x2, y2 — y grows downward)."""

    x1: float
    y1: float
    x2: float
    y2: float


class GroundResponse(BaseModel):
    phrase: str
    timestamp: float
    boxes: list[GroundBox]


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

    min_score = settings.search_min_similarity_effective
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

    # Caption channel (Florence-2): match the query against each frame's stored
    # caption embedding — text↔text, which nails relational/detail prompts
    # ("the guy with long hair standing next to the car") that image embeddings
    # only gesture at. A frame whose caption says the thing is pulled up to the
    # match band even when the raw image similarity is lukewarm. Frames without
    # captions simply don't participate. No separate pass through query_expand:
    # the variants are already visual phrasings, exactly what captions are.
    caption_floor = settings.caption_min_similarity
    for variant in variants:
        query_vector = await run_in_threadpool(embedder.embed_text, variant)
        distance = Frame.caption_embedding.cosine_distance(query_vector)
        result = await db.execute(
            select(
                Frame.id,
                Frame.timestamp_sec,
                (1 - distance).label("similarity"),
            )
            .where(
                Frame.video_id == video_id,
                Frame.caption_embedding.is_not(None),
                # Pre-filter in SQL: below the caption floor, discounting won't
                # rescue it — no point shipping the similarity back.
                (1 - distance) >= caption_floor,
            )
        )
        for row in result.all():
            boosted = float(row.similarity) * _CAPTION_WEIGHT
            current = best.get(row.id)
            if current is None or boosted > current[1]:
                best[row.id] = (row.timestamp_sec, boosted, str(row.id))

    frames = sorted(best.values(), key=lambda frame: frame[0])
    # Keyframe sampling spaces frames by content, not at a fixed rate. A video
    # whose samples sit 6s apart cannot have a 2s window mean what it means at
    # 1 fps — every scene would split into one clip per frame — so widen it to
    # the video's real spacing. Only when the samples really are sparser than
    # the configured interval: at nominal density the configured window is a
    # deliberate choice and stands.
    spacing = _sample_spacing(frames)
    if spacing > settings.frame_interval_seconds:
        merge_window = max(merge_window, spacing * 1.5)
    scenes = _merge_scenes(frames, min_score, merge_window)

    # Curation pass: a scene must clear both the absolute floor (above) and
    # this relative bar against the best scene in the result set. Without it,
    # a query with one strong hit ships a tail of 30–50% "matches" — scenes
    # that cleared the absolute floor only because the prompt was vague, and
    # that read as the video containing things it doesn't.
    if scenes:
        top = max(
            max(frame[1] for frame in scene) for scene in scenes
        )
        floor = max(min_score, top * _RELATIVE_FLOOR)
        scenes = [
            scene for scene in scenes if max(frame[1] for frame in scene) >= floor
        ]

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


def _sample_spacing(frames) -> float:
    """Median gap between this video's frames, or 0 when there is nothing to go on.

    The median rather than the mean: one long gap (a stretch of video with no
    keyframe) must not stretch the merge window for the whole video.
    """
    if len(frames) < 2:
        return 0.0
    gaps = sorted(later[0] - earlier[0] for earlier, later in zip(frames, frames[1:], strict=False))
    return gaps[len(gaps) // 2]


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
        "embedding model and returns the scenes (merged runs of matching "
        "frames) whose "
        "visual content is close enough, with timestamps and similarity "
        "scores. Returns an empty list when nothing in the video matches."
    ),
    responses={
        404: {"description": "Video not found"},
        409: {"description": "Video is still being indexed"},
    },
)
async def search_clips(
    access: RequestUserDep,
    db: DbSession,
    payload: ClipSearchRequest,
) -> ClipSearchResponse:
    # Trial-aware rather than account-only: the public homepage's whole job
    # is to let an anonymous visitor search the video they just uploaded.
    # Registered users resolve through the same dependency and see no
    # difference; only the surrounding product features are gated.
    try:
        video = await videos_service.get_video(db, access.user.id, payload.video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc

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
    )


@router.post(
    "/{video_id}/ground",
    response_model=GroundResponse,
    summary="Locate a phrase inside one frame (visual grounding)",
    description=(
        "Runs Florence-2 phrase grounding on the frame at `timestamp` and "
        "returns bounding boxes (normalised 0-1) for every occurrence of the "
        "phrase. Empty `boxes` means the model found nothing there. Requires "
        "`grounding_enabled` in settings; returns 503 when it is off."
    ),
    responses={
        404: {"description": "Video not found, or no frame at that timestamp"},
        503: {"description": "Grounding is disabled on this deployment"},
    },
)
async def ground_phrase(
    access: RequestUserDep,
    db: DbSession,
    video_id: uuid.UUID,
    payload: GroundRequest,
) -> GroundResponse:
    if not settings.grounding_enabled:
        raise HTTPException(status_code=503, detail="Grounding is not enabled")

    try:
        video = await videos_service.get_video(db, access.user.id, video_id)
    except videos_service.VideoNotFound as exc:
        raise HTTPException(status_code=404, detail="Video not found") from exc

    if video.status != "ready":
        raise HTTPException(status_code=409, detail="Video is still being indexed")

    # Decode the frame off the loop, then run the model off the loop — both
    # are CPU-bound, and together they are roughly a second of work.
    try:
        local_path = await run_in_threadpool(storage.get_local_path, video.storage_key)
        frame = await run_in_threadpool(
            pipeline.frame_at, local_path, payload.timestamp
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - unreadable storage is a 500
        raise HTTPException(status_code=500, detail="Could not read video file") from exc

    boxes = await run_in_threadpool(captions.locate_phrase, frame, payload.phrase)
    return GroundResponse(
        phrase=payload.phrase,
        timestamp=payload.timestamp,
        boxes=[
            GroundBox(x1=b[0], y1=b[1], x2=b[2], y2=b[3])
            for b in boxes
            if len(b) == 4
        ],
    )
