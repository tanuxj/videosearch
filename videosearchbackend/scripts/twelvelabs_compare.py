"""Index a video with Twelve Labs and compare its search against local CLIP.

Standalone on purpose: it touches no application routes and writes nothing to
the videos/frames tables, so it can be run against a live database to judge
whether Marengo is worth adopting before any of it is wired into the app.

    # index one video, then search it both ways
    uv run python scripts/twelvelabs_compare.py --video <uuid> --query "a red car"

    # search only (the video is already indexed remotely)
    uv run python scripts/twelvelabs_compare.py --video <uuid> --query "..." --no-index

Videos are handed over as a presigned R2 URL, so nothing is downloaded here.
"""

import argparse
import asyncio
import sys
import time
import uuid

import app.db.metadata  # noqa: F401 - registers every table so FKs resolve
from app.core.config import get_settings
from app.db.session import SessionFactory
from app.videos import twelvelabs
from app.videos.models import Video
from app.videos.storage import storage

settings = get_settings()

# How long to wait for remote indexing before giving up, and how often to ask.
POLL_SECONDS = 10.0
MAX_WAIT_SECONDS = 3600.0

# Statuses that mean the job is over, one way or the other.
_DONE = {"ready", "completed", "done", "indexed"}
_FAILED = {"failed", "error", "cancelled"}


def _timecode(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


async def _load_video(video_id: uuid.UUID) -> Video:
    async with SessionFactory() as db:
        video = await db.get(Video, video_id)
        if video is None:
            raise SystemExit(f"No video with id {video_id}")
        return video


def _source_url(video: Video) -> str:
    """A presigned URL Twelve Labs can fetch the object from directly."""
    url = storage.presign_get(video.storage_key, expires_in=3600)
    if not url:
        raise SystemExit(
            "Storage cannot presign (local backend?) — Twelve Labs needs a "
            "publicly reachable URL to pull the video from."
        )
    return url


def _index_remotely(video: Video) -> str:
    index_id = twelvelabs.ensure_index()
    print(f"index: {index_id}")

    started = time.perf_counter()
    asset_id = twelvelabs.create_asset_from_url(_source_url(video), video.name)
    print(f"asset: {asset_id}")

    indexed_id = twelvelabs.index_asset(index_id, asset_id)
    print(f"indexing {video.name!r} ({(video.duration_seconds or 0) / 60:.1f} min)…")

    while True:
        state = twelvelabs.indexed_asset(index_id, indexed_id)
        status = str(state.get("status") or state.get("state") or "").lower()
        elapsed = time.perf_counter() - started
        print(f"  [{elapsed:6.1f}s] {status or '(no status field)'}")

        if status in _DONE:
            print(f"--- indexed in {elapsed:.1f}s ---")
            return index_id
        if status in _FAILED:
            raise SystemExit(f"Remote indexing failed: {state}")
        if elapsed > MAX_WAIT_SECONDS:
            raise SystemExit(f"Gave up after {MAX_WAIT_SECONDS:.0f}s; last state: {state}")
        time.sleep(POLL_SECONDS)


async def _clip_search(video: Video, query: str, limit: int) -> list[tuple[float, float, float]]:
    """The app's own CLIP search, for the side-by-side column.

    Calls `run_clip_search` — the same function the search route and the
    URL-import auto-extract job use — so the comparison is against exactly
    what the app serves today, not a reimplementation of it.
    """
    from app.videos.search import run_clip_search

    async with SessionFactory() as db:
        result = await run_clip_search(
            db,
            video.id,
            query,
            limit=limit,
            duration_seconds=video.duration_seconds,
        )
    return [(item.start, item.end, item.score) for item in result.items]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, help="Video UUID from the videos table")
    parser.add_argument("--query", required=True, help="Natural-language search prompt")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Skip upload/indexing — the video is already in the remote index",
    )
    args = parser.parse_args()

    if not settings.twelvelabs_configured:
        raise SystemExit("Set TWELVELABS_API_KEY in .env first.")

    video = await _load_video(uuid.UUID(args.video))
    print(f"video: {video.name}  ({video.frames_indexed} CLIP frames indexed)\n")

    index_id = (
        twelvelabs.ensure_index()
        if args.no_index
        else await asyncio.to_thread(_index_remotely, video)
    )

    print(f"\n=== query: {args.query!r} ===\n")

    started = time.perf_counter()
    hits = await asyncio.to_thread(twelvelabs.search, index_id, args.query, args.limit)
    tl_ms = (time.perf_counter() - started) * 1000
    print(f"--- Twelve Labs ({tl_ms:.0f} ms) ---")
    if not hits:
        print("  (no matches)")
    for hit in hits:
        print(f"  #{hit.rank}  {_timecode(hit.start)}–{_timecode(hit.end)}")
        if hit.transcription:
            print(f"        “{hit.transcription[:72]}”")

    started = time.perf_counter()
    try:
        scenes = await _clip_search(video, args.query, args.limit)
        clip_ms = (time.perf_counter() - started) * 1000
        print(f"\n--- local CLIP ({clip_ms:.0f} ms) ---")
        if not scenes:
            print("  (no matches above the similarity floor)")
        for start, end, score in scenes:
            print(f"  {_timecode(start)}–{_timecode(end)}  score={score:.3f}")
    except Exception as exc:  # noqa: BLE001 - comparison column is best-effort
        print(f"\n--- local CLIP unavailable: {exc}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
