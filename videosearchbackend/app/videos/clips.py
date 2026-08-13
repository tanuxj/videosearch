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
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class ClipError(Exception):
    """The segment could not be extracted from the source video."""


def ffmpeg_binary() -> str:
    """Path to a working ffmpeg executable (bundled via imageio-ffmpeg)."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def trim(source: Path, start: float, end: float, out: Path) -> Path:
    """Cut ``[start, end)`` seconds from ``source`` into ``out`` (an .mp4).

    Raises ``ClipError`` if neither the fast copy nor the re-encode succeeds.
    """
    duration = max(0.0, end - start)
    if duration <= 0:
        raise ClipError(f"Empty clip: start={start} end={end}")

    binary = ffmpeg_binary()
    if _try_run(binary, _copy_cmd(binary, source, start, duration, out)) and _usable(out):
        logger.info("Clip extracted (stream copy): %s -> %s", source.name, out.name)
        return out

    # Re-encode fallback: accurate cut, H.264/AAC in MP4.
    logger.warning("Stream-copy trim failed for %s — re-encoding instead", source.name)
    if not (_try_run(binary, _encode_cmd(binary, source, start, duration, out)) and _usable(out)):
        raise ClipError(f"ffmpeg produced no usable clip for {source.name}")
    logger.info("Clip extracted (re-encode): %s -> %s", source.name, out.name)
    return out


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


def _copy_cmd(binary: str, source: Path, start: float, duration: float, out: Path) -> list[str]:
    """Fast path: seek + stream-copy, keyframe-aligned, fast-start MP4."""
    return [
        binary,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
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


def _encode_cmd(binary: str, source: Path, start: float, duration: float, out: Path) -> list[str]:
    """Accurate cut with re-encode to H.264/AAC."""
    return [
        binary,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
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
