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


def _read_sampled_chunk(
    cap, start_frame: int, step: int, count: int, fps: float
) -> tuple[list[np.ndarray], list[float], int]:
    """Read up to `count` sampled frames from `start_frame`, stepping by `step`.

    Returns (rgb_frames, timestamps, next_frame_index). Seeking per chunk
    keeps memory flat for arbitrarily long videos.
    """
    rgb_frames: list[np.ndarray] = []
    timestamps: list[float] = []
    frame_index = start_frame
    read = 0

    while read < count:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            break
        rgb_frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        timestamps.append(frame_index / fps)
        frame_index += step
        read += 1

    return rgb_frames, timestamps, frame_index


def _process_video(path: Path, emit) -> tuple[float, int, int]:
    """Worker-thread body: decode + embed + emit chunks.

    `emit(timestamps, embeddings)` is called on the worker thread with one
    chunk at a time; the async caller bridges it onto the event loop.
    Returns (duration_seconds, total_frames, frames_indexed).
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video file: {path.name}")

    try:
        fps, total_frames = _probe(cap)
        step = max(1, round(fps * settings.frame_interval_seconds))
        duration = total_frames / fps if total_frames else 0.0
        expected = total_frames // step if total_frames else 0

        indexed = 0
        frame_index = 0
        while True:
            rgb_frames, timestamps, frame_index = _read_sampled_chunk(
                cap, frame_index, step, _EMBED_CHUNK, fps
            )
            if not rgb_frames:
                break
            embeddings = embedder.embed_images(rgb_frames)
            emit(timestamps, embeddings)
            indexed += len(timestamps)
            if len(timestamps) < _EMBED_CHUNK:
                break

        return duration, expected, indexed
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


async def index_video(video_id: uuid.UUID) -> None:
    """Run the full indexing pipeline for one video. Idempotent per video.

    Safe to call more than once: a video that is not ``processing`` is left
    alone. Runs its own session so it is independent of any request.
    """
    local_path: Path | None = None
    try:
        async with SessionFactory() as db:
            video = await db.get(Video, video_id)
            if video is None or video.status != "processing":
                return

            local_path = await asyncio.to_thread(storage.get_local_path, video.storage_key)

            queue: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def emit(timestamps: list, embeddings: list) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, (_CHUNK, timestamps, embeddings))

            def worker() -> None:
                try:
                    stats = _process_video(local_path, emit)
                    loop.call_soon_threadsafe(queue.put_nowait, (_DONE, stats))
                except Exception as exc:  # pragma: no cover - surfaced via queue
                    loop.call_soon_threadsafe(queue.put_nowait, (_ERROR, exc))

            # Worker runs on a thread; consumer runs here on the loop.
            worker_task = asyncio.create_task(asyncio.to_thread(worker))

            duration = total_frames = 0.0
            while True:
                kind, *payload = await queue.get()
                if kind == _CHUNK:
                    timestamps, embeddings = payload
                    await _insert_chunk(db, video, timestamps, embeddings)
                elif kind == _DONE:
                    duration, total_frames, _ = payload[0]
                    break
                elif kind == _ERROR:
                    raise payload[0]

            await worker_task

            video.duration_seconds = duration
            video.frames_total = total_frames
            video.status = "ready"
            await db.commit()
            logger.info(
                "Indexed video %s: %d frames over %.1fs",
                video_id,
                video.frames_indexed,
                duration,
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
        # R2 objects were copied to a temp file for processing.
        if local_path is not None and storage.backend == "r2":
            local_path.unlink(missing_ok=True)
