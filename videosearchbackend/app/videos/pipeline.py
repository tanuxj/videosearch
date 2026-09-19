"""Indexing pipeline: extract frames → CLIP-embed → persist to pgvector.

Runs as an in-process background job (FastAPI ``BackgroundTasks``), one per
upload. Design notes:

* **Keyframes, not every frame.** Sampling asks ffmpeg for keyframes only
  (``-skip_frame nokey``), so the decoder skips every predicted frame in
  between instead of decoding the whole stream to throw most of it away.
  Encoders put keyframes at cuts, which is exactly where a scene search wants
  samples. Measured ~4x faster than the full decode on a 2s-GOP 720p file and
  far more on longer GOPs. Stretches with no keyframe are filled by a second,
  ranged pass so a static shot still contributes frames.
* **CPU work off the event loop, and overlapped.** Decode and embed run on two
  worker threads with a bounded hand-off queue — they used to alternate in one
  thread, where each stalled the other. Results stream back through an
  ``asyncio.Queue`` so the async side only does DB writes, and the API keeps
  serving requests while a video indexes.
* **Bounded memory.** Frames leave the decoder already scaled to CLIP's 224x224
  input, one chunk at a time, and the async consumer persists each chunk
  immediately — so a long video never holds more than a few dozen small frames.
* **Real progress.** ``frames_total`` is set up front (estimated from duration)
  and ``frames_indexed`` increments per chunk, so the frontend's status poll
  shows live progress. Keyframe sampling means the up-front number is only an
  estimate, so the consumer re-projects it from the keep/candidate ratio each
  chunk and it converges to the real count.
* **Failure is explicit.** Any exception marks the video ``failed`` with the
  error message instead of leaving it stuck in ``processing`` forever.
* **Transcription runs alongside, not after.** Speech recognition is seconds
  of work against minutes for CLIP, so it is started as its own task on its
  own session the moment the file is probed. Its progress is reported through
  ``transcript_status``, independent of ``status``, so subtitles and the
  transcript reach the user long before the visual index is done.
"""

import asyncio
import collections
import contextlib
import logging
import math
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.notifications import service as notifications_service
from app.videos import captions, embedder, transcribe
from app.videos.clips import ffmpeg_binary
from app.videos.models import Frame, TranscriptSegment, Video
from app.videos.storage import storage

logger = logging.getLogger(__name__)
settings = get_settings()

# Frames per embedding chunk — small enough to bound memory, large enough to
# amortise CLIP's per-call overhead. Bigger than it was now that embedding has
# its own thread: a larger batch means fewer hand-offs for the same work.
_EMBED_CHUNK = 64

# Chunks allowed to sit between the decode thread and the embed thread. Two is
# enough to keep the embedder fed across a slow read without letting a fast
# decoder build an unbounded backlog of decoded frames.
_QUEUE_DEPTH = 2

# Queue item kinds.
_CHUNK = "chunk"
_DONE = "done"
_ERROR = "error"

# Frames leave the sampler already at CLIP's input size: the decoder does the
# scale and centre-crop, so no full-resolution frame is ever copied into Python.
_SAMPLE_SIZE = embedder.CLIP_INPUT_SIZE
_SAMPLE_BYTES = _SAMPLE_SIZE * _SAMPLE_SIZE * 3

# Container timestamps are floats: an exact `>=` against a 1.0s interval would
# drop the frame that lands on 0.9999999.
_EPSILON = 1e-3

# Timestamps are rounded to milliseconds before they reach the database. The
# `(video_id, timestamp_sec)` unique constraint is what would otherwise turn a
# sampler reporting one frame twice into a failed index.
_TS_PLACES = 3

# ffmpeg's `showinfo` filter logs one line per frame reaching the output, in
# output order — that ordering is what pairs a timestamp with its frame.
_PTS_TIME = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")

# Longest wait for the timestamp line belonging to a frame already read off
# stdout. showinfo logs it before the frame is muxed, so this only trips when
# ffmpeg isn't logging what we asked for.
_PTS_WAIT_SECONDS = 30.0

# Scale until the short edge reaches 224, centre-crop to 224x224 — the same
# preprocessing CLIP's own processor applies, so these vectors stay
# interchangeable with everything indexed before — then log the timestamps.
_SAMPLE_FILTER = (
    f"scale={_SAMPLE_SIZE}:{_SAMPLE_SIZE}:force_original_aspect_ratio=increase,"
    f"crop={_SAMPLE_SIZE}:{_SAMPLE_SIZE},showinfo"
)


class SamplerUnavailable(Exception):
    """ffmpeg could not sample this file — the caller falls back to OpenCV."""


class _Stats(NamedTuple):
    """What one indexing run did, for the completion log line."""

    indexed: int
    decode_seconds: float
    embed_seconds: float
    sampler: str
    filled: int


class AudioOnlyFile(Exception):
    """The file has an audio track but no video — nothing to frame-index.

    Raised by :func:`probe_file` when OpenCV can't open the file and ffmpeg
    confirms it simply has no video stream (a mic-only recording saved as
    .webm, for instance). The pipeline then skips frame extraction entirely
    and marks the video ready once its audio is transcribed.
    """

    def __init__(self, *, duration: float) -> None:
        super().__init__(f"no video track (duration={duration:.2f}s)")
        self.duration = duration


# ffmpeg's `-i` output marks each stream as "Stream #0:0(eng): Video: …" or
# "… Audio: …" and the container's length as "Duration: HH:MM:SS.mmm".
_ANY_STREAM = re.compile(r"Stream #\d+:\d+")
_VIDEO_STREAM = re.compile(r"Stream #\d+:\d+.*: Video:")
_DURATION = re.compile(r"Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


def _probe_audio_only_duration(path: Path) -> float | None:
    """Duration (seconds) of an audio-only file, or None when it isn't one.

    ``cv2.VideoCapture`` cannot open audio-only containers, so when the
    OpenCV probe fails the pipeline asks ffmpeg whether the file simply has
    no video track. Returns the duration when the file is readable media
    without a video stream, and None when ffmpeg couldn't read it at all or
    the file does carry a video track — both of those are genuine failures,
    not a skipped index.
    """
    result = subprocess.run(  # noqa: S603 - fixed binary, no shell
        [ffmpeg_binary(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    stderr = result.stderr or ""
    # A non-media blob produces no container header at all (no Duration, no
    # streams) — that's an unreadable file, not an audio-only one.
    if not _DURATION.search(stderr) and not _ANY_STREAM.search(stderr):
        return None
    # It has a video track: cv2 failing to open it is a real problem.
    if _VIDEO_STREAM.search(stderr):
        return None
    match = _DURATION.search(stderr)
    if match is None:
        return 0.0
    hours, minutes, seconds = (float(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _probe(cap) -> tuple[float, int]:
    """(fps, frame_count) from a VideoCapture, with sane fallbacks."""
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not fps or fps <= 0 or not np.isfinite(fps):
        fps = 25.0
    if frames <= 0:
        frames = 0
    return float(fps), frames


def probe_file(path: Path) -> tuple[float, int]:
    """(duration_seconds, expected_sample_count) for a video file.

    Cheap — reads container metadata only, no decoding. Run before indexing
    starts so ``frames_total`` is known up front and the status poll can show
    real progress instead of 0/0.

    The count is the fixed-rate ceiling (one sample per
    ``frame_interval_seconds``). Keyframe sampling normally lands well under
    it, so the indexing consumer re-projects the denominator as it goes.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        # cv2 can't open audio-only containers. When ffmpeg confirms the file
        # is media without a video track, there is nothing to frame-index —
        # the caller marks the video ready once its audio is transcribed.
        duration = _probe_audio_only_duration(path)
        if duration is not None:
            raise AudioOnlyFile(duration=duration)
        raise RuntimeError(f"Could not open video file: {path.name}")
    try:
        fps, total_frames = _probe(cap)
    finally:
        cap.release()

    duration = total_frames / fps if total_frames else 0.0
    # Ceiling, not floor: the sample at t=0 counts, so 14.3s at one sample a
    # second is 15 samples (0, 1, … 14) — flooring reported 14 and made the
    # progress bar read 15/14.
    expected = math.ceil(duration / settings.frame_interval_seconds) if duration else 0
    return duration, expected


def _scene_key(frame: np.ndarray) -> np.ndarray:
    """Tiny grayscale proxy of a sampled frame, for comparing successive ones.

    36x64 downscaled gray is a few hundred bytes and `mean abs diff` on it is
    far cheaper than the CLIP embed it can skip — an obvious cost to pay on
    static-heavy footage.
    """
    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), (64, 36))


def _read_exactly(stream, size: int) -> bytes | None:
    """Read exactly `size` bytes from `stream`, or None once it ends.

    A pipe's ``read(n)`` returns *up to* n bytes, so one call routinely comes
    back with a partial frame — reassembling here is what stops frames from
    being torn apart and misaligned against their timestamps.
    """
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        part = stream.read(remaining)
        if not part:
            return None
        chunks.append(part)
        remaining -= len(part)
    return b"".join(chunks)


def _sampler_args(
    path: Path,
    *,
    keyframes_only: bool,
    seek: float | None = None,
    span: float | None = None,
    rate: float | None = None,
) -> list[str]:
    """ffmpeg argv that pipes 224x224 RGB frames to stdout, timestamps to stderr.

    ``-vsync 0`` matters: without it the rawvideo muxer is free to duplicate
    frames up to a constant rate, which would break the one-line-per-frame
    pairing with `showinfo`. It is spelled the old way on purpose —
    ``-fps_mode`` only exists from ffmpeg 5.1, and a system ffmpeg can be older.

    ``-threads`` is capped at ``decode_threads`` so the decoder and the
    embedder share the box instead of each claiming every core.
    """
    args = [ffmpeg_binary(), "-hide_banner", "-loglevel", "info"]
    # Capped, not left to ffmpeg's "one thread per core" default: decoding and
    # embedding run concurrently (see `_process_video`), so an unbounded
    # decoder takes cores straight off the embedder — which is the half of the
    # job that is actually the bottleneck. Before `-i`: this is a decode option.
    args += ["-threads", str(settings.decode_threads)]
    if keyframes_only:
        # Decoder-level: non-keyframes are discarded before being decoded.
        args += ["-skip_frame", "nokey"]
    # Both before `-i`: an input seek jumps to the nearest preceding keyframe
    # instead of decoding the whole file up to the mark.
    if seek is not None:
        args += ["-ss", f"{seek:.3f}"]
    if span is not None:
        args += ["-t", f"{span:.3f}"]
    args += ["-i", str(path), "-an", "-sn", "-dn", "-vsync", "0"]
    filters = _SAMPLE_FILTER if rate is None else f"fps={rate:.6f},{_SAMPLE_FILTER}"
    args += ["-vf", filters, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    return args


def _ffmpeg_samples(args: list[str], *, offset: float = 0.0) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (timestamp, RGB frame) pairs from an ffmpeg rawvideo pipe.

    Frames arrive on stdout as fixed-size rgb24 buffers; their timestamps
    arrive on stderr as `showinfo` lines, one per frame, in the same order. A
    reader thread keeps stderr drained — a full stderr pipe would deadlock
    ffmpeg — and hands the timestamps over in order.

    `offset` is added to every timestamp. An input ``-ss`` seek rebases the
    stream to zero (measured: a pass seeked to 60s reports its first frame at
    0.0), so a ranged fill pass reports times relative to its own start.

    Raises :class:`SamplerUnavailable` when a frame arrives with no timestamp to
    pair it with — a wrong timestamp would point a clip at the wrong moment, so
    the run falls back to OpenCV rather than guessing — and when ffmpeg exits
    non-zero, which otherwise reads as "the video ended here" and would leave a
    half-indexed video marked ready.
    """
    proc = subprocess.Popen(  # noqa: S603 - fixed binary, no shell
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
    )
    timestamps: queue.Queue = queue.Queue()
    # Last few non-showinfo log lines, kept for the error message when ffmpeg
    # exits non-zero — the reason is always in there somewhere.
    complaints: collections.deque = collections.deque(maxlen=5)

    def drain() -> None:
        try:
            try:
                for line in iter(proc.stderr.readline, b""):
                    text = line.decode("utf-8", "replace").strip()
                    match = _PTS_TIME.search(text)
                    if match is not None:
                        timestamps.put(float(match.group(1)))
                    elif text:
                        complaints.append(text)
            except ValueError:
                # The generator's finally closes stderr while this thread may
                # still be blocked inside readline() — that race surfaces here
                # as "I/O operation on closed file" and means end-of-stream
                # just the same. The sentinel below is what matters.
                pass
        finally:
            # Sentinel: stderr closed, so no further timestamp is coming.
            timestamps.put(None)

    reader = threading.Thread(target=drain, name="ffmpeg-showinfo", daemon=True)
    reader.start()
    try:
        while True:
            buffer = _read_exactly(proc.stdout, _SAMPLE_BYTES)
            if buffer is None:
                break
            try:
                pts = timestamps.get(timeout=_PTS_WAIT_SECONDS)
            except queue.Empty:
                raise SamplerUnavailable("ffmpeg logged no timestamp for a frame") from None
            if pts is None:
                raise SamplerUnavailable("ffmpeg stopped logging timestamps")
            frame = np.frombuffer(buffer, dtype=np.uint8).reshape(_SAMPLE_SIZE, _SAMPLE_SIZE, 3)
            yield pts + offset, frame
        # Reaching here is a real end of stream, so the exit status is
        # meaningful (below, `terminate` is what ends an abandoned generator and
        # its status says nothing). A file ffmpeg cannot read at all exits
        # non-zero having produced nothing, which is how the fallback is reached.
        proc.stdout.close()
        if proc.wait(timeout=30) != 0:
            reader.join(timeout=5)
            raise SamplerUnavailable(
                f"ffmpeg exited {proc.returncode}: {' | '.join(complaints) or 'no output'}"
            )
    finally:
        # Closing the pipes makes ffmpeg exit on its next write if it is still
        # running (an abandoned generator, a failure upstream).
        for pipe in (proc.stdout, proc.stderr):
            with contextlib.suppress(Exception):
                pipe.close()
        if proc.poll() is None:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
        reader.join(timeout=5)


def _keyframe_samples(
    path: Path, *, interval: float, max_gap: float, duration: float
) -> Iterator[tuple[float, np.ndarray]]:
    """Keyframes thinned to `interval` spacing, then sampling gaps filled.

    Two properties of real files drive this:

    * Most encoders emit a keyframe at every cut, so keyframe-only decoding
      lands the frames a scene search wants and skips the rest of the stream.
    * All-intra footage (MJPEG, ProRes, some screen recorders) makes *every*
      frame a keyframe, which is why the `interval` thinning below is not
      optional — without it such a file would embed at full frame rate.

    Sparse-keyframe footage is the opposite problem: a locked-off camera or a
    single-GOP screen recording can leave minutes with no keyframe at all.
    Those stretches are filled afterwards by ranged passes, so samples are not
    yielded in timestamp order — nothing downstream depends on that
    (``search_clips`` sorts by timestamp), and the alternative is seeking
    backwards mid-stream, which is what makes decoding slow in the first place.
    """
    # A gap only needs filling once it exceeds the sampling interval too —
    # `scene_max_gap_seconds` below `frame_interval_seconds` is a legal config.
    gap_limit = max(max_gap, interval)
    gaps: list[tuple[float, float]] = []
    last_kept: float | None = None

    for timestamp, frame in _ffmpeg_samples(_sampler_args(path, keyframes_only=True)):
        if last_kept is not None and timestamp - last_kept > gap_limit:
            gaps.append((last_kept, timestamp))
        if last_kept is None or timestamp - last_kept >= interval - _EPSILON:
            last_kept = timestamp
            yield timestamp, frame

    # The tail is a gap like any other: a keyframe at 0:20 of an hour-long
    # static shot must not leave the remaining 59 minutes unsampled.
    if last_kept is not None and duration - last_kept > gap_limit:
        gaps.append((last_kept, duration))

    for start, end in gaps:
        # Start one step in: the frame at `start` is the keyframe already
        # yielded, and re-emitting it would collide on its timestamp.
        fill_start = start + gap_limit
        span = end - fill_start
        if span <= _EPSILON:
            continue
        logger.debug("Filling %.1fs sampling gap at %.1fs in %s", span, fill_start, path.name)
        try:
            yield from _ffmpeg_samples(
                _sampler_args(
                    path, keyframes_only=False, seek=fill_start, span=span, rate=1.0 / gap_limit
                ),
                offset=fill_start,
            )
        except SamplerUnavailable as exc:
            # Filling a gap is enrichment on top of a keyframe index that
            # already exists — a seek ffmpeg refuses costs a few samples in one
            # stretch, which is not worth failing the whole video over.
            logger.warning(
                "Could not fill the %.1fs gap at %.1fs in %s: %s",
                span,
                fill_start,
                path.name,
                exc,
            )


def _opencv_samples(path: Path, *, interval: float) -> Iterator[tuple[float, np.ndarray]]:
    """Fixed-rate samples via OpenCV — the fallback when ffmpeg cannot sample.

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
        step = max(1, round(fps * interval))
        index = 0
        while cap.grab():
            if index % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                # Match the ffmpeg path: RGB, already at CLIP's input size.
                yield index / fps, embedder.to_clip_frame(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            index += 1
    finally:
        cap.release()


def _iter_samples(
    path: Path, *, sampler: str, interval: float, max_gap: float, duration: float
) -> Iterator[tuple[float, np.ndarray]]:
    """Sample one video, cheapest viable path first.

    The ffmpeg keyframe sampler is the fast path; OpenCV is the fallback for
    anything it cannot read. The fallback only applies before the first frame
    is yielded — switching samplers mid-file would re-emit frames the caller
    has already embedded.
    """
    if sampler == "opencv":
        yield from _opencv_samples(path, interval=interval)
        return

    yielded = 0
    try:
        for sample in _keyframe_samples(
            path, interval=interval, max_gap=max_gap, duration=duration
        ):
            yielded += 1
            yield sample
    except (SamplerUnavailable, OSError, subprocess.SubprocessError) as exc:
        if yielded:
            raise
        logger.warning(
            "ffmpeg sampling of %s unavailable (%s) — falling back to OpenCV", path.name, exc
        )
        yield from _opencv_samples(path, interval=interval)


def _process_video(
    path: Path,
    emit,
    *,
    sampler: str,
    interval: float,
    max_gap: float,
    duration: float,
    scene_aware: bool,
    scene_threshold: float,
) -> _Stats:
    """Worker-thread body: sample + embed, emitting one chunk at a time.

    `emit(timestamps, embeddings, kept, candidates)` is called from the embed
    thread with one chunk at a time; the async caller bridges it onto the event
    loop. `kept`/`candidates` are running totals so the caller can re-estimate
    the progress denominator — the up-front metadata count is the fixed-rate
    ceiling, not what keyframe sampling actually embeds.

    Sampling and embedding run on separate threads with a bounded hand-off
    queue. They used to alternate in one thread, where decoding sat idle for the
    length of every embed and vice versa; both release the GIL (ffmpeg is a
    subprocess, onnxruntime releases it around inference), so overlapping them
    is close to free.

    Scene-aware sampling then drops samples whose picture did not really
    change: a sample is embedded when its mean absolute pixel difference (on the
    grayscale proxy) versus the last kept one reaches `scene_threshold`, or when
    `max_gap` seconds have passed since the last keep. On a fixed-GOP encode —
    keyframes every 2s whatever is happening on screen — this is what stops a
    long static shot from being embedded over and over.

    Returns the run's stats; `decode_seconds` and `embed_seconds` overlap in
    wall-clock time and must not be summed.
    """
    work: queue.Queue = queue.Queue(maxsize=_QUEUE_DEPTH)
    # Written by the embed thread, read here once it has been joined.
    state: dict = {"indexed": 0, "embed_seconds": 0.0, "error": None}

    def embed_worker() -> None:
        while True:
            item = work.get()
            if item is None:
                return
            timestamps, frames, kept, candidates = item
            try:
                started = time.perf_counter()
                embeddings = embedder.embed_images(frames)
                # Captioning rides the same thread: it is CPU-bound like the
                # embedder, and the frames are already in hand. Failure is
                # chunk-local — those frames just keep their (null) caption,
                # and search falls back to the embedding for them.
                chunk_captions: list[str] | None = None
                caption_vectors: list[list[float]] | None = None
                if settings.captions_enabled:
                    try:
                        chunk_captions = captions.caption_frames(frames)
                        caption_vectors = embedder.embed_texts(chunk_captions)
                    except Exception:  # noqa: BLE001 - captions are optional
                        logger.exception(
                            "Captioning failed for a chunk of video (frames keep null captions)"
                        )
                state["embed_seconds"] += time.perf_counter() - started
                emit(timestamps, embeddings, kept, candidates, chunk_captions, caption_vectors)
                state["indexed"] += len(timestamps)
            except Exception as exc:  # noqa: BLE001 - re-raised by the sampler below
                state["error"] = exc
                return

    def submit(item) -> None:
        """Hand a chunk to the embed thread, or re-raise that thread's failure.

        The timeout is what keeps a dead embed thread from parking the sampler
        on a full queue forever.
        """
        while True:
            if state["error"] is not None:
                raise state["error"]
            try:
                work.put(item, timeout=0.5)
                return
            except queue.Full:
                continue

    thread = threading.Thread(target=embed_worker, name="clip-embed", daemon=True)
    thread.start()
    started = time.perf_counter()
    used_sampler = "opencv" if sampler == "opencv" else "keyframe"
    frames: list[np.ndarray] = []
    timestamps: list[float] = []
    # Guards the frames table's (video_id, timestamp_sec) unique constraint: a
    # container with duplicate keyframe timestamps must not fail the index.
    seen: set[float] = set()
    kept = 0
    candidates = 0
    filled = 0
    last_key: np.ndarray | None = None
    last_kept_time: float | None = None

    try:
        for timestamp, frame in _iter_samples(
            path, sampler=sampler, interval=interval, max_gap=max_gap, duration=duration
        ):
            stamp = round(timestamp, _TS_PLACES)
            if stamp in seen:
                continue
            candidates += 1
            if last_kept_time is not None and timestamp < last_kept_time:
                # Out of order, so this is a gap-fill sample — by definition
                # from a stretch the keyframe pass had nothing for.
                filled += 1

            keep = True
            key = _scene_key(frame) if scene_aware else None
            if key is not None and last_key is not None:
                difference = float(
                    np.mean(np.abs(key.astype(np.int16) - last_key.astype(np.int16)))
                )
                stale = last_kept_time is None or timestamp - last_kept_time >= max_gap
                keep = difference >= scene_threshold or stale
            if not keep:
                continue

            if key is not None:
                last_key = key
            last_kept_time = timestamp
            seen.add(stamp)
            kept += 1
            frames.append(frame)
            timestamps.append(stamp)
            if len(frames) == _EMBED_CHUNK:
                submit((timestamps, frames, kept, candidates))
                frames, timestamps = [], []

        if frames:
            submit((timestamps, frames, kept, candidates))
    finally:
        # The sentinel has to go in even on the failure path, or the embed
        # thread never returns.
        with contextlib.suppress(Exception):
            work.put(None, timeout=30)
        thread.join(timeout=300)

    if state["error"] is not None:
        raise state["error"]
    return _Stats(
        indexed=state["indexed"],
        decode_seconds=time.perf_counter() - started,
        embed_seconds=state["embed_seconds"],
        sampler=used_sampler,
        filled=filled,
    )


def frame_at(path: Path, timestamp: float) -> np.ndarray:
    """Decode one RGB frame at `timestamp` seconds, at the model's input size.

    Serves on-demand grounding: the lightbox asks "where is X in this frame",
    and Florence-2 needs the pixels. Input seek (-ss before -i) jumps to the
    nearest preceding keyframe and decodes forward from there — one frame is
    cheap. Raises the same OpenCV error path as `probe_file` if the file
    cannot be opened at all; an empty decode (timestamp past the end) raises
    ValueError, which the route maps to 404-level "no such frame".
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video file: {path.name}")
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise ValueError(f"No frame at {timestamp:.2f}s")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


async def _insert_chunk(
    db: AsyncSession,
    video: Video,
    timestamps: list,
    embeddings: list,
    captions: list[str] | None = None,
    caption_embeddings: list | None = None,
) -> None:
    """Write one chunk of frames (and captions, when captioning ran) and bump the counter."""
    rows = []
    for i, (ts, emb) in enumerate(zip(timestamps, embeddings, strict=True)):
        row = {"video_id": video.id, "timestamp_sec": ts, "embedding": emb}
        if captions is not None and i < len(captions):
            row["caption"] = captions[i]
            if caption_embeddings is not None and i < len(caption_embeddings):
                row["caption_embedding"] = caption_embeddings[i]
        rows.append(row)
    await db.execute(insert(Frame), rows)
    video.frames_indexed += len(timestamps)
    await db.commit()


async def _mark_transcript(video_id: uuid.UUID, status: str, error: str | None) -> None:
    """Record a terminal transcription outcome. Best effort — never raises."""
    try:
        async with SessionFactory() as db:
            video = await db.get(Video, video_id)
            if video is None:
                return
            video.transcript_status = status
            video.transcript_error = error[:500] if error else None
            await db.commit()
    except Exception:  # pragma: no cover - best effort
        logger.exception("Could not record transcript status for video %s", video_id)


async def _run_transcription(video_id: uuid.UUID, source: Path, duration: float) -> None:
    """Transcribe one video and persist its segments. Never raises.

    Runs on its own session, concurrently with frame embedding. That is
    deliberate rather than incidental: committing here is what makes the
    transcript readable while ``status`` is still ``processing``.

    Sharing a row across two sessions is safe because SQLAlchemy only writes
    the columns each session actually changed — the frame loop's commits touch
    ``frames_indexed``/``status``, this one touches ``transcript_status``, and
    neither clobbers the other's.
    """
    if not settings.transcription_configured:
        await _mark_transcript(video_id, "skipped", None)
        return

    work_dir = Path(tempfile.mkdtemp(prefix="vs-transcribe-"))
    try:
        async with SessionFactory() as db:
            video = await db.get(Video, video_id)
            if video is None:
                return
            video.transcript_status = "processing"
            await db.commit()

        started = time.perf_counter()
        result = await asyncio.to_thread(transcribe.transcribe, source, duration, work_dir)
        elapsed = time.perf_counter() - started

        async with SessionFactory() as db:
            video = await db.get(Video, video_id)
            if video is None:
                return
            # Re-running the pipeline on a video must not double the transcript.
            await db.execute(
                delete(TranscriptSegment).where(TranscriptSegment.video_id == video_id)
            )
            if result.segments:
                await db.execute(
                    insert(TranscriptSegment),
                    [
                        {
                            "video_id": video_id,
                            "idx": index,
                            "start_sec": segment.start,
                            "end_sec": segment.end,
                            "text": segment.text,
                        }
                        for index, segment in enumerate(result.segments)
                    ],
                )
            video.language = result.language
            video.transcript_status = "ready"
            video.transcript_error = None
            await db.commit()

        logger.info(
            "Transcribed video %s: %d segments, language=%s, in %.1fs",
            video_id,
            len(result.segments),
            result.language or "unknown",
            elapsed,
        )
    except transcribe.NoAudioTrack as exc:
        # A silent video is a normal thing to upload, not a failure.
        logger.info("No audio to transcribe for video %s: %s", video_id, exc)
        await _mark_transcript(video_id, "skipped", None)
    except Exception as exc:  # noqa: BLE001 - transcription must not fail indexing
        logger.exception("Transcription failed for video %s", video_id)
        await _mark_transcript(video_id, "failed", str(exc))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def transcribe_existing(video_id: uuid.UUID) -> None:
    """Run only the transcription pass on an already-indexed video.

    Frames are left completely alone. This exists because a video indexed
    before transcription was added — or one whose transcription failed, or
    that was indexed while no ASR key was configured — otherwise has no route
    to a transcript short of deleting and re-uploading it.
    """
    local_path: Path | None = None
    owns_local_file = False
    try:
        async with SessionFactory() as db:
            video = await db.get(Video, video_id)
            if video is None:
                return
            storage_key = video.storage_key
            duration = video.duration_seconds or 0.0

        # Same ownership rule as the indexing path: the local backend hands
        # back the stored object itself, which must survive.
        local_path = await asyncio.to_thread(storage.get_local_path, storage_key)
        owns_local_file = storage.backend == "r2"

        # If the file has no usable duration recorded, transcribe it whole —
        # `_chunk_audio` treats 0 as "shorter than the chunk limit".
        await _run_transcription(video_id, local_path, duration)
    except Exception as exc:  # noqa: BLE001 - must not escape a background task
        logger.exception("Re-transcription failed for video %s", video_id)
        await _mark_transcript(video_id, "failed", str(exc))
    finally:
        if local_path is not None and owns_local_file:
            local_path.unlink(missing_ok=True)


async def index_video(
    video_id: uuid.UUID,
    source_path: Path | None = None,
    *,
    own_source: bool = True,
) -> None:
    """Run the full indexing pipeline for one video. Idempotent per video.

    Safe to call more than once: a video that is not ``processing`` is left
    alone. Runs its own session so it is independent of any request.

    `source_path` is a local copy of the bytes the upload handler already had in
    hand. Passing it skips re-downloading the object that was just uploaded —
    for the R2 backend that round trip measured ~0.36 s/MB. Ownership transfers
    to this function by default: the file is deleted when indexing finishes or
    fails. Pass ``own_source=False`` when the caller still needs the bytes — the
    URL import uploads the same file to storage while this runs.
    """
    local_path: Path | None = source_path
    # Only remove files we own — for the local backend `get_local_path` returns
    # the stored object itself, which must survive.
    owns_local_file = source_path is not None and own_source
    transcript_task: asyncio.Task | None = None
    try:
        async with SessionFactory() as db:
            video = await db.get(Video, video_id)
            if video is None or video.status != "processing":
                return

            if local_path is None or not local_path.exists():
                local_path = await asyncio.to_thread(storage.get_local_path, video.storage_key)
                owns_local_file = storage.backend == "r2"

            # Publish the denominator before any embedding work so the frontend
            # poll shows progress from the first tick. With scene-aware sampling
            # this is the fixed-rate ceiling; the consumer re-projects it per
            # chunk from the keep/candidate ratio.
            try:
                duration, expected = await asyncio.to_thread(probe_file, local_path)
            except AudioOnlyFile as exc:
                # No video track (a mic-only recording, say): there is nothing
                # to frame-index. Record the duration, mark the video ready
                # immediately, and transcribe its audio — for a recording, the
                # transcript is the point. Transcription is its own task, as in
                # the normal path below, so the `ready` row lands now and the
                # `finally` block keeps the file alive until it finishes.
                video.duration_seconds = exc.duration
                video.has_video = False
                video.frames_total = 0
                video.frames_indexed = 0
                video.status = "ready"
                await db.commit()
                # The uploader's bell rings: indexing is done (nothing to
                # frame-index, but the video is searchable by transcript).
                await notifications_service.create_notification(
                    db, user_id=video.owner_id, video_id=video.id
                )
                transcript_task = asyncio.create_task(
                    _run_transcription(video_id, local_path, exc.duration)
                )
                return
            video.duration_seconds = duration
            video.has_video = True
            video.frames_total = expected
            await db.commit()

            # Kicked off here, before any embedding: the transcript typically
            # lands within seconds, so the user is reading it while the bar
            # below it is still filling. Awaited in `finally` — the local file
            # must outlive it.
            transcript_task = asyncio.create_task(
                _run_transcription(video_id, local_path, duration)
            )

            # Named "chunks" rather than "queue": the stdlib queue module is
            # imported for the sampler threads, and shadowing it here would be a
            # trap for the next reader.
            chunks: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def emit(
                timestamps: list,
                embeddings: list,
                kept: int,
                candidates: int,
                chunk_captions: list[str] | None,
                caption_vectors: list | None,
            ) -> None:
                loop.call_soon_threadsafe(
                    chunks.put_nowait,
                    (_CHUNK, timestamps, embeddings, kept, candidates,
                     chunk_captions, caption_vectors),
                )

            def worker() -> None:
                try:
                    stats = _process_video(
                        local_path,
                        emit,
                        sampler=settings.frame_sampler,
                        interval=settings.frame_interval_seconds,
                        max_gap=settings.scene_max_gap_seconds,
                        duration=duration,
                        scene_aware=settings.scene_aware_sampling,
                        scene_threshold=settings.scene_threshold,
                    )
                    loop.call_soon_threadsafe(chunks.put_nowait, (_DONE, stats))
                except Exception as exc:  # pragma: no cover - surfaced via queue
                    loop.call_soon_threadsafe(chunks.put_nowait, (_ERROR, exc))

            # Worker runs on a thread; consumer runs here on the loop.
            started = time.perf_counter()
            worker_task = asyncio.create_task(asyncio.to_thread(worker))

            stats = _Stats(0, 0.0, 0.0, settings.frame_sampler, 0)
            db_seconds = 0.0
            while True:
                kind, *payload = await chunks.get()
                if kind == _CHUNK:
                    (timestamps, embeddings, kept, candidates,
                     chunk_captions, caption_vectors) = payload
                    if candidates > 0:
                        # Re-project the denominator toward what will actually be
                        # embedded so the progress bar tracks real completion
                        # instead of sitting at ~30% then jumping to 100%.
                        projected = math.ceil(expected * kept / candidates)
                        video.frames_total = max(video.frames_indexed, projected)
                    insert_started = time.perf_counter()
                    await _insert_chunk(
                        db, video, timestamps, embeddings, chunk_captions, caption_vectors
                    )
                    db_seconds += time.perf_counter() - insert_started
                elif kind == _DONE:
                    stats = payload[0]
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
            # The uploader's bell rings: the video is now searchable. Written
            # after the ready commit on purpose — a failed notification must
            # never roll back a finished index.
            await notifications_service.create_notification(
                db, user_id=video.owner_id, video_id=video.id
            )
            logger.info(
                "Indexed video %s: %d frames over %.1fs of video in %.1fs "
                "(sampler %s, %d gap-filled; sample %.1fs and embed %.1fs overlap, "
                "db %.1fs)",
                video_id,
                video.frames_indexed,
                video.duration_seconds or 0.0,
                wall_seconds,
                stats.sampler,
                stats.filled,
                stats.decode_seconds,
                stats.embed_seconds,
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
        # Transcription reads the same local file, so it has to finish before
        # the file goes away — including on the failure path, where frames blew
        # up but the transcript may still be mid-flight. It swallows its own
        # errors; `suppress` is for cancellation propagating in.
        if transcript_task is not None:
            with contextlib.suppress(Exception):
                await transcript_task
        # Either the upload handler's spilled copy or a temp file downloaded
        # from R2. Never the stored object itself (local backend).
        if local_path is not None and owns_local_file:
            local_path.unlink(missing_ok=True)
