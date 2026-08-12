"""Indexing pipeline: extract frames → CLIP-embed → persist to pgvector.

Runs as an in-process background job (FastAPI ``BackgroundTasks``), one per
upload. Design notes:

* **CPU work off the event loop.** Decoding + embedding run inside a worker
  thread; results stream back through an ``asyncio.Queue`` so the async side
  only does DB writes. The API keeps serving requests while a video indexes.
* **Bounded memory.** The worker emits one chunk of ~32 frames at a time and
  the async consumer persists it immediately, so a long video never holds
  more than a few dozen decoded frames in memory.
* **Real progress.** ``frames_total`` is set up front (from the file's frame
  count) and ``frames_indexed`` increments per chunk, so the frontend's
  status poll shows live progress.
* **Failure is explicit.** Any exception marks the video ``failed`` with the
  error message instead of leaving it stuck in ``processing`` forever.
"""

import asyncio
import logging
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.videos import embedder
from app.videos.models import Frame, Video
from app.videos.storage import storage

logger = logging.getLogger(__name__)
settings = get_settings()

# Frames per embedding chunk — small enough to bound memory, large enough to
# amortise CLIP's per-call overhead.
_EMBED_CHUNK = 32

# Queue item kinds.
_CHUNK = "chunk"
_DONE = "done"
_ERROR = "error"


def _probe(cap) -> tuple[float, int]:
    """(fps, frame_count) from a VideoCapture, with sane fallbacks."""
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not fps or fps <= 0 or not np.isfinite(fps):
        fps = 25.0
    if frames <= 0:
        frames = 0
    return float(fps), frames


def probe_file(path: Path) -> tuple[float, float, int]:
    """(duration_seconds, sample_step, expected_sample_count) for a video file.

    Cheap — reads container metadata only, no decoding. Run before indexing
    starts so ``frames_total`` is known up front and the status poll can show
    real progress instead of 0/0.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video file: {path.name}")
    try:
        fps, total_frames = _probe(cap)
    finally:
        cap.release()

    step = max(1, round(fps * settings.frame_interval_seconds))
    duration = total_frames / fps if total_frames else 0.0
    # Ceiling, not floor: frame 0 is sampled, so a 429-frame clip at step 30
    # yields 15 samples (0, 30, … 420) — flooring reported 14 and made the
    # progress bar read 15/14.
    expected = -(-total_frames // step) if total_frames else 0
    return duration, step, expected


def _process_video(path: Path, step: int, emit) -> tuple[int, float, float]:
    """Worker-thread body: decode + embed + emit chunks.

    Returns (frames_indexed, decode_seconds, embed_seconds) — the split is
    logged on completion so a slow index can be attributed without a profiler.

    `emit(timestamps, embeddings)` is called on the worker thread with one chunk
    at a time; the async caller bridges it onto the event loop.

    Decoding is a single forward pass: ``grab()`` advances the demuxer without
    decoding and only sampled frames are ``retrieve()``d. Seeking per frame
    instead (``CAP_PROP_POS_FRAMES``) forces a re-decode from the preceding
    keyframe on every read, which measured ~2x slower even on a keyframe-dense
    file and far worse on normal H.264.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video file: {path.name}")

    try:
        fps, _ = _probe(cap)
        frames: list[np.ndarray] = []
        timestamps: list[float] = []
        indexed = 0
        frame_index = 0
        embed_seconds = 0.0
        started = time.perf_counter()

        def flush() -> tuple[int, float]:
            embed_started = time.perf_counter()
            embeddings = embedder.embed_images(frames)
            elapsed = time.perf_counter() - embed_started
            emit(list(timestamps), embeddings)
            count = len(timestamps)
            frames.clear()
            timestamps.clear()
            return count, elapsed

        while cap.grab():
            if frame_index % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                timestamps.append(frame_index / fps)
                if len(frames) == _EMBED_CHUNK:
                    count, elapsed = flush()
                    indexed += count
                    embed_seconds += elapsed
            frame_index += 1

        if frames:
            count, elapsed = flush()
            indexed += count
            embed_seconds += elapsed

        total = time.perf_counter() - started
        return indexed, max(0.0, total - embed_seconds), embed_seconds
    finally:
        cap.release()


async def _insert_chunk(
    db: AsyncSession,
    video: Video,
    timestamps: list,
    embeddings: list,
) -> None:
    """Write one chunk of frames and bump the indexed counter."""
    await db.execute(
        insert(Frame),
        [
            {"video_id": video.id, "timestamp_sec": ts, "embedding": emb}
            for ts, emb in zip(timestamps, embeddings, strict=True)
        ],
    )
    video.frames_indexed += len(timestamps)
    await db.commit()


async def index_video(video_id: uuid.UUID, source_path: Path | None = None) -> None:
    """Run the full indexing pipeline for one video. Idempotent per video.

    Safe to call more than once: a video that is not ``processing`` is left
    alone. Runs its own session so it is independent of any request.

    `source_path` is a local copy of the bytes the upload handler already had in
    hand. Passing it skips re-downloading the object that was just uploaded —
    for the R2 backend that round trip measured ~0.36 s/MB. Ownership transfers
    to this function: the file is deleted when indexing finishes or fails.
    """
    local_path: Path | None = source_path
    # Only remove files we own — for the local backend `get_local_path` returns
    # the stored object itself, which must survive.
    owns_local_file = source_path is not None
    try:
        async with SessionFactory() as db:
            video = await db.get(Video, video_id)
            if video is None or video.status != "processing":
                return

            if local_path is None or not local_path.exists():
                local_path = await asyncio.to_thread(storage.get_local_path, video.storage_key)
                owns_local_file = storage.backend == "r2"

            # Publish the denominator before any embedding work so the frontend
            # poll shows progress from the first tick.
            duration, step, expected = await asyncio.to_thread(probe_file, local_path)
            video.duration_seconds = duration
            video.frames_total = expected
            await db.commit()

            queue: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def emit(timestamps: list, embeddings: list) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, (_CHUNK, timestamps, embeddings))

            def worker() -> None:
                try:
                    stats = _process_video(local_path, step, emit)
                    loop.call_soon_threadsafe(queue.put_nowait, (_DONE, stats))
                except Exception as exc:  # pragma: no cover - surfaced via queue
                    loop.call_soon_threadsafe(queue.put_nowait, (_ERROR, exc))

            # Worker runs on a thread; consumer runs here on the loop.
            started = time.perf_counter()
            worker_task = asyncio.create_task(asyncio.to_thread(worker))

            decode_seconds = embed_seconds = db_seconds = 0.0
            while True:
                kind, *payload = await queue.get()
                if kind == _CHUNK:
                    timestamps, embeddings = payload
                    insert_started = time.perf_counter()
                    await _insert_chunk(db, video, timestamps, embeddings)
                    db_seconds += time.perf_counter() - insert_started
                elif kind == _DONE:
                    _, decode_seconds, embed_seconds = payload[0]
                    break
                elif kind == _ERROR:
                    raise payload[0]

            await worker_task
            wall_seconds = time.perf_counter() - started

            # The metadata estimate can be off by a frame on files with an
            # imprecise frame count; settle the denominator on what was actually
            # indexed so a finished video always reads exactly 100%.
            video.frames_total = video.frames_indexed
            video.status = "ready"
            await db.commit()
            logger.info(
                "Indexed video %s: %d frames over %.1fs of video in %.1fs "
                "(decode %.1fs, embed %.1fs, db %.1fs)",
                video_id,
                video.frames_indexed,
                video.duration_seconds or 0.0,
                wall_seconds,
                decode_seconds,
                embed_seconds,
                db_seconds,
            )
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded
        logger.exception("Indexing failed for video %s", video_id)
        try:
            async with SessionFactory() as db:
                video = await db.get(Video, video_id)
                if video is not None and video.status == "processing":
                    # Drop frames inserted by chunks that committed before the
                    # failure, so a `failed` video leaves no searchable index.
                    await db.execute(delete(Frame).where(Frame.video_id == video.id))
                    video.status = "failed"
                    video.error = str(exc)[:500]
                    await db.commit()
        except Exception:  # pragma: no cover - best effort
            logger.exception("Could not mark video %s as failed", video_id)
    finally:
        # Either the upload handler's spilled copy or a temp file downloaded
        # from R2. Never the stored object itself (local backend).
        if local_path is not None and owns_local_file:
            local_path.unlink(missing_ok=True)
