"""Clip extraction: cut a stored video down to a [start, end) segment.

The ffmpeg binary is bundled by ``imageio-ffmpeg`` (a pure-pip dependency with
static binaries for Windows, macOS and Linux), so the backend can trim videos
on any host without a system ffmpeg install — local dev machines and the
production Docker image alike.

Trim strategy:

* **Fast path** — ``-c copy`` stream-copies the segment out of the source. No
  re-encode, near-instant, no quality loss. The cut snaps to the nearest
  keyframe before ``start``, which is exactly what players and editors do.
* **Fallback** — re-encode to H.264/AAC when the stream-copy fails (e.g. an
  audio codec the container rejects, or a source that cannot be remuxed).

The source may be a local path **or an https URL**. Handing ffmpeg a URL is the
whole reason clip download is fast: with ``-ss`` before ``-i`` it seeks the
remote file with HTTP range requests and pulls only the bytes around the cut.
Downloading the object first meant fetching a 1.4 GB movie to keep four
seconds of it — minutes of transfer for a job that takes milliseconds.
"""

import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Source can be a local file or a remote URL ffmpeg opens itself.
type Source = Path | str


def _is_remote(source: Source) -> bool:
    return isinstance(source, str) and source.startswith(("http://", "https://"))


def _label(source: Source) -> str:
    """Short name for logs — never the full URL, which carries a signature."""
    if _is_remote(source):
        return str(source).split("?", 1)[0].rsplit("/", 1)[-1] or "remote"
    return Path(source).name


class ClipError(Exception):
    """The segment could not be extracted from the source video."""


def _bundled_binary() -> str:
    """The imageio-ffmpeg static build — always present, local files only."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


@lru_cache(maxsize=1)
def ffmpeg_binary() -> str:
    """Path to a working ffmpeg executable.

    Prefers a system ffmpeg (``$FFMPEG_BINARY``, else ``PATH``) and falls back
    to the binary bundled by imageio-ffmpeg. The order matters — see
    :func:`supports_network_input`.
    """
    override = os.environ.get("FFMPEG_BINARY")
    if override:
        return override
    return shutil.which("ffmpeg") or _bundled_binary()


@lru_cache(maxsize=1)
def supports_network_input() -> bool:
    """Whether the selected ffmpeg can read an ``http(s)`` source.

    The imageio-ffmpeg fallback is a **statically linked glibc** build, and
    static glibc cannot resolve hostnames: ``getaddrinfo`` has to ``dlopen`` the
    NSS modules, which a static binary has no loader for. The result is not an
    error message but a straight **SIGSEGV with empty stderr** on any URL input,
    including plain public ones. Only a dynamically linked system ffmpeg is safe
    for URLs, so callers must check this before handing over a presigned link.
    """
    try:
        return ffmpeg_binary() != _bundled_binary()
    except Exception:  # noqa: BLE001 - imageio-ffmpeg missing entirely
        return True


def trim(source: Source, start: float, end: float, out: Path) -> Path:
    """Cut ``[start, end)`` seconds from ``source`` into ``out`` (an .mp4).

    ``source`` is a local path or an https URL; a URL is read in place with
    range requests rather than downloaded whole.

    Raises ``ClipError`` if neither the fast copy nor the re-encode succeeds.
    """
    duration = max(0.0, end - start)
    if duration <= 0:
        raise ClipError(f"Empty clip: start={start} end={end}")

    name = _label(source)
    binary = ffmpeg_binary()

    # Three attempts, cheapest first. The middle one matters more than it looks:
    # the usual reason a full stream-copy fails is an audio codec MP4 cannot
    # hold (PCM out of a .mov, for instance) while the video track is perfectly
    # copyable. On a 41 MB pcm_s24le .mov, re-encoding only the audio measured
    # 23.0s against 40.4s for re-encoding both streams.
    attempts = (
        ("stream copy", _copy_cmd),
        ("copy video, re-encode audio", _copy_video_cmd),
        ("re-encode", _encode_cmd),
    )
    for label, build in attempts:
        if _try_run(binary, build(binary, source, start, duration, out)) and _usable(out):
            logger.info("Clip extracted (%s): %s -> %s", label, name, out.name)
            return out
        logger.warning("Trim via %s failed for %s", label, name)

    raise ClipError(f"ffmpeg produced no usable clip for {name}")


def _input_args(source: Source, start: float) -> list[str]:
    """Seek + input flags shared by both commands.

    ``-ss`` goes *before* ``-i``: that is what makes ffmpeg seek instead of
    decoding from the top, and over HTTP it turns into a range request.

    The reconnect flags only exist on the http protocol — passing them with a
    file input makes ffmpeg exit with "Option not found", so they are added
    only for remote sources. Without them a dropped socket mid-cut fails the
    whole request instead of resuming.
    """
    args = ["-ss", f"{start:.3f}"]
    if _is_remote(source):
        args += [
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_on_network_error",
            "1",
            "-reconnect_delay_max",
            "5",
        ]
    return args + ["-i", str(source)]


def _try_run(binary: str, cmd: list[str]) -> bool:
    """Run ffmpeg; True only when it exits 0. Raises ClipError on hard failures."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise ClipError(f"ffmpeg timed out: {cmd[:4]}...") from exc
    except OSError as exc:
        raise ClipError(f"ffmpeg could not run ({binary}): {exc}") from exc
    if result.returncode != 0:
        logger.warning("ffmpeg exited %d: %s", result.returncode, result.stderr.strip()[-400:])
        return False
    return True


def _copy_cmd(binary: str, source: Source, start: float, duration: float, out: Path) -> list[str]:
    """Fast path: seek + stream-copy, keyframe-aligned, fast-start MP4."""
    return [
        binary,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *_input_args(source, start),
        "-t",
        f"{duration:.3f}",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        str(out),
    ]


def _copy_video_cmd(
    binary: str, source: Source, start: float, duration: float, out: Path
) -> list[str]:
    """Middle path: keep the video stream as-is, re-encode only the audio.

    Covers the common failure where MP4 rejects the source's audio codec (PCM
    from a .mov, for example) but the video track would have copied fine.
    """
    return [
        binary,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *_input_args(source, start),
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        # Subtitle and data tracks are what usually break the mux; a clip does
        # not need them.
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        str(out),
    ]


def _encode_cmd(binary: str, source: Source, start: float, duration: float, out: Path) -> list[str]:
    """Accurate cut with re-encode to H.264/AAC."""
    return [
        binary,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *_input_args(source, start),
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(out),
    ]


def _usable(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0
