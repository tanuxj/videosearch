"""Frame sampling: what the indexing pipeline feeds CLIP, and when.

No database and no model — these run the real ffmpeg sampler over generated
files and check the samples that come back. The three cases are the ones the
sampler is actually shaped around:

* a normal encode, where keyframes sit at a regular GOP boundary,
* all-intra footage (MJPEG, ProRes, screen recorders), where *every* frame is a
  keyframe and thinning is the only thing keeping the embed count sane,
* sparse-keyframe footage, where whole minutes can carry no keyframe and the
  gap-fill pass is the only reason those minutes get indexed at all.

Timestamps matter as much as frame counts here: they are what a clip's start and
end are computed from, so a sampler that pairs a frame with the wrong time sends
the user to the wrong moment.
"""

import subprocess

import numpy as np
import pytest

from app.videos import embedder, pipeline
from app.videos.clips import ffmpeg_binary


def _encode(path, *, seconds: int, gop: int, rate: int = 30) -> None:
    """Write an H.264 test file with a known keyframe interval.

    `-sc_threshold 0` disables scene-cut keyframes, so `gop` is exactly the
    keyframe spacing rather than a ceiling on it.
    """
    subprocess.run(
        [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=320x240:rate={rate}:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            str(gop),
            "-sc_threshold",
            "0",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _samples(path, *, interval: float, max_gap: float, duration: float) -> list:
    return list(
        pipeline._iter_samples(
            path,
            sampler="keyframe",
            interval=interval,
            max_gap=max_gap,
            duration=duration,
        )
    )


def test_keyframe_sampler_returns_keyframes_at_their_own_timestamps(tmp_path) -> None:
    """A 2s GOP over 10s yields the 5 keyframes, timestamped where they sit."""
    path = tmp_path / "gop2.mp4"
    _encode(path, seconds=10, gop=60)  # 30fps, keyframe every 2s

    samples = _samples(path, interval=1.0, max_gap=6.0, duration=10.0)

    assert [round(ts, 1) for ts, _ in samples] == [0.0, 2.0, 4.0, 6.0, 8.0]
    # Frames arrive already cropped to CLIP's input, so the embedder never sees
    # a full-resolution frame and no resize happens twice.
    for _, frame in samples:
        assert frame.shape == (embedder.CLIP_INPUT_SIZE, embedder.CLIP_INPUT_SIZE, 3)
        assert frame.dtype == np.uint8


def test_keyframe_sampler_thins_all_intra_footage_to_the_interval(tmp_path) -> None:
    """Every frame being a keyframe must not mean embedding every frame.

    An all-intra file at 10 fps offers 30 keyframes over 3 seconds; at a 1s
    interval only ~3 of them should come back.
    """
    path = tmp_path / "allintra.mp4"
    # `-g 1`: every frame is its own keyframe, the all-intra case.
    subprocess.run(
        [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=10:duration=3",
            "-c:v",
            "libx264",
            "-g",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )

    samples = _samples(path, interval=1.0, max_gap=6.0, duration=3.0)

    assert [round(ts, 1) for ts, _ in samples] == [0.0, 1.0, 2.0]


def test_keyframe_sampler_fills_stretches_with_no_keyframe(tmp_path) -> None:
    """A single-keyframe file still gets sampled across its whole length.

    This is the screen-recording case: one keyframe at 0:00 and nothing after
    it. Without the fill pass the video would be indexed by exactly one frame.
    """
    path = tmp_path / "sparse.mp4"
    _encode(path, seconds=12, gop=600)  # one keyframe, at t=0

    samples = _samples(path, interval=1.0, max_gap=3.0, duration=12.0)
    times = sorted(round(ts, 1) for ts, _ in samples)

    # The keyframe, then a fill every `max_gap` seconds to the end.
    assert times == [0.0, 3.0, 6.0, 9.0]


def test_keyframe_sampler_timestamps_survive_the_fill_pass(tmp_path) -> None:
    """A fill frame's timestamp is absolute, not relative to its own pass.

    ffmpeg rebases an input `-ss` seek to zero, so a ranged pass reports its
    first frame at 0.0. Getting this wrong would point every gap-filled clip at
    the start of the video.
    """
    path = tmp_path / "sparse-mid.mp4"
    _encode(path, seconds=20, gop=600)

    samples = _samples(path, interval=1.0, max_gap=5.0, duration=20.0)
    fills = [round(ts, 1) for ts, _ in samples if ts > 0]

    assert fills, "expected gap fills for a file with one keyframe"
    assert min(fills) == pytest.approx(5.0, abs=0.5)
    assert max(fills) == pytest.approx(15.0, abs=0.5)


def test_opencv_sampler_matches_the_ffmpeg_contract(tmp_path) -> None:
    """The fallback yields the same shape of samples at a fixed rate."""
    path = tmp_path / "gop2.mp4"
    _encode(path, seconds=5, gop=60)

    samples = list(pipeline._opencv_samples(path, interval=1.0))

    assert [round(ts, 1) for ts, _ in samples] == [0.0, 1.0, 2.0, 3.0, 4.0]
    for _, frame in samples:
        assert frame.shape == (embedder.CLIP_INPUT_SIZE, embedder.CLIP_INPUT_SIZE, 3)


def test_unreadable_file_falls_back_and_then_fails(tmp_path) -> None:
    """A non-video is a failure, not a silent zero-frame index.

    ffmpeg cannot sample it, so the sampler falls back to OpenCV — which cannot
    open it either, and raises. The pipeline turns that into a `failed` video.
    """
    path = tmp_path / "junk.mp4"
    path.write_bytes(b"this is not a video at all")

    with pytest.raises(RuntimeError, match="Could not open video file"):
        _samples(path, interval=1.0, max_gap=6.0, duration=0.0)
