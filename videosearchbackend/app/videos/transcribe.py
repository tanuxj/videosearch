"""Speech → timed text, via any OpenAI-compatible ``/audio/transcriptions``.

The point of this module is speed. CLIP frame embedding is minutes of work;
Whisper-turbo on a hosted inference endpoint is seconds. Keeping the two apart
(see ``pipeline.py``) means the user reads the transcript and sees subtitles
while the visual index is still building, instead of waiting for both.

What it does, in order:

1. **Extract audio, not video.** ffmpeg pulls a mono 16 kHz stream out of the
   file — Whisper resamples to that anyway, so sending anything richer is
   upload time spent for nothing. An hour of video becomes a few MB.
2. **Chunk it.** Providers cap upload size (Groq at 25 MB on the free tier),
   and chunks transcribe *concurrently*, so a 3-hour recording finishes in
   roughly the time of its slowest chunk rather than the sum of all of them.
   Offsets are exact by construction: each chunk is cut with an explicit
   ``-ss``, so its segment times shift by exactly that value.
3. **Transcribe and stitch.** Segments are re-numbered contiguously and their
   timestamps rebased onto the full video's timeline.

The ffmpeg binary is the one ``clips.py`` already resolves — bundled by
imageio-ffmpeg, so no system install is needed.

The HTTP call uses ``urllib`` deliberately, matching ``query_expand.py``: the
caller runs this on a worker thread, so a blocking stdlib request costs nothing
and the production image gains no dependency.
"""

import json
import logging
import re
import secrets
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.videos.clips import ffmpeg_binary

logger = logging.getLogger(__name__)
settings = get_settings()


class TranscriptionError(Exception):
    """The audio could not be transcribed."""


class NoAudioTrack(TranscriptionError):
    """The source file carries no audio stream — nothing to transcribe."""


@dataclass(frozen=True, slots=True)
class Segment:
    """One timed utterance on the full video's timeline."""

    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class Transcript:
    language: str | None
    segments: list[Segment]


# Whisper reports the language as an English name ("english", "hindi"), but a
# WebVTT track's `srclang` wants a BCP-47 code. These are the languages the
# model is strongest on; anything outside the table is stored as the model
# said it, which still displays — only the browser's language label suffers.
_LANGUAGE_CODES = {
    "arabic": "ar",
    "bengali": "bn",
    "bulgarian": "bg",
    "catalan": "ca",
    "chinese": "zh",
    "croatian": "hr",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "estonian": "et",
    "filipino": "fil",
    "finnish": "fi",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "gujarati": "gu",
    "hebrew": "he",
    "hindi": "hi",
    "hungarian": "hu",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "kannada": "kn",
    "korean": "ko",
    "latvian": "lv",
    "lithuanian": "lt",
    "malay": "ms",
    "malayalam": "ml",
    "marathi": "mr",
    "nepali": "ne",
    "norwegian": "no",
    "persian": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "punjabi": "pa",
    "romanian": "ro",
    "russian": "ru",
    "serbian": "sr",
    "slovak": "sk",
    "slovenian": "sl",
    "spanish": "es",
    "swahili": "sw",
    "swedish": "sv",
    "tamil": "ta",
    "telugu": "te",
    "thai": "th",
    "turkish": "tr",
    "ukrainian": "uk",
    "urdu": "ur",
    "vietnamese": "vi",
}

# Tried in order — the first the bundled ffmpeg can actually encode wins.
# Opus is ~10x smaller than WAV at speech quality; PCM is the floor that every
# build supports, and chunking keeps even its bulk under the upload cap.
_AUDIO_CODECS: tuple[tuple[str, str, list[str]], ...] = (
    ("opus", ".ogg", ["-c:a", "libopus", "-b:a", settings.stt_audio_bitrate]),
    ("mp3", ".mp3", ["-c:a", "libmp3lame", "-q:a", "9"]),
    ("pcm", ".wav", ["-c:a", "pcm_s16le"]),
)

_MIME_TYPES = {".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".wav": "audio/wav"}

# ffmpeg prints stream layout to stderr; this is how we tell "silent video"
# from "transcription is broken" before spending a single API call.
_AUDIO_STREAM = re.compile(r"Stream #\d+:\d+.*: Audio:")

# Sent on every ASR request, and not optional. urllib defaults to
# `Python-urllib/3.x`, which Cloudflare (in front of api.groq.com, among
# others) blocks outright — the reply is a 403 carrying "error code: 1010",
# which looks exactly like a bad API key and is not one.
_USER_AGENT = "videosearch/0.1 (+https://github.com/tanuxj/videosearch)"


def _run(args: list[str], timeout: float = 600.0) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed binary, no shell
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def has_audio(source: Path) -> bool:
    """Whether the file contains an audio stream.

    ``ffmpeg -i`` with no output exits non-zero by design and writes the
    stream table to stderr — the exit code is meaningless here, the text is
    what matters.
    """
    result = _run([ffmpeg_binary(), "-hide_banner", "-i", str(source)], timeout=60.0)
    return bool(_AUDIO_STREAM.search(result.stderr or ""))


def extract_audio(source: Path, out_dir: Path) -> Path:
    """Write ``source``'s audio to a mono 16 kHz file in ``out_dir``.

    Tries each codec in ``_AUDIO_CODECS`` until one succeeds: which encoders a
    given ffmpeg build carries is not guaranteed, and falling back to PCM means
    the feature never hard-fails on an unusual build.
    """
    errors: list[str] = []
    for name, suffix, codec_args in _AUDIO_CODECS:
        out = out_dir / f"audio{suffix}"
        result = _run(
            [
                ffmpeg_binary(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",  # drop the video stream entirely
                "-ac",
                "1",  # mono
                "-ar",
                "16000",  # what Whisper resamples to anyway
                *codec_args,
                str(out),
            ]
        )
        if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
            logger.info(
                "Extracted %s audio for %s (%d bytes)", name, source.name, out.stat().st_size
            )
            return out
        errors.append(f"{name}: {(result.stderr or '').strip()[:200]}")
        out.unlink(missing_ok=True)

    raise TranscriptionError("Could not extract audio — " + " | ".join(errors))


def _chunk_audio(audio: Path, duration: float, out_dir: Path) -> list[tuple[float, Path]]:
    """Split ``audio`` into ``(offset_seconds, path)`` pieces.

    Each piece is cut with an explicit ``-ss``/``-t`` and a stream copy, so its
    offset into the original is exactly the value we asked for. Cutting with
    ``-f segment`` instead would be one pass rather than N seeks, but its
    boundaries land on the nearest packet *after* the requested time and the
    drift accumulates across a long file — subtitles that slide later and later
    are worse than a few extra milliseconds of seeking.
    """
    limit = settings.stt_chunk_seconds
    if duration <= limit:
        return [(0.0, audio)]

    chunks: list[tuple[float, Path]] = []
    index = 0
    offset = 0.0
    while offset < duration:
        out = out_dir / f"chunk{index:04d}{audio.suffix}"
        result = _run(
            [
                ffmpeg_binary(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                # -ss before -i seeks rather than decoding up to the mark.
                "-ss",
                f"{offset:.3f}",
                "-t",
                f"{limit:.3f}",
                "-i",
                str(audio),
                "-c",
                "copy",
                str(out),
            ]
        )
        if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            out.unlink(missing_ok=True)
            # A tail chunk that lands past the real end produces nothing —
            # that is the end of the file, not a failure.
            if chunks:
                break
            raise TranscriptionError(
                f"Could not split audio: {(result.stderr or '').strip()[:200]}"
            )
        chunks.append((offset, out))
        offset += limit
        index += 1

    logger.info("Split %.0fs of audio into %d chunks", duration, len(chunks))
    return chunks


def _multipart(fields: dict[str, str], filename: str, blob: bytes, mime: str) -> tuple[bytes, str]:
    """Encode form fields plus one file as a multipart/form-data body."""
    boundary = f"----videosearch{secrets.token_hex(16)}"
    body = bytearray()
    for name, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    body += f"--{boundary}\r\n".encode()
    body += (
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode()
    body += blob
    body += f"\r\n--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _transcribe_chunk(path: Path) -> dict:
    """POST one audio file and return the provider's ``verbose_json`` body."""
    fields = {
        "model": settings.stt_model,
        "response_format": "verbose_json",
        # Segment-level times are what WebVTT cues and a readable transcript
        # both want; word-level would be ~20x the rows for no visible gain.
        "timestamp_granularities[]": "segment",
        # Deterministic: retries return the same text rather than drifting.
        "temperature": "0",
    }
    if settings.stt_language:
        fields["language"] = settings.stt_language

    blob = path.read_bytes()
    mime = _MIME_TYPES.get(path.suffix, "application/octet-stream")
    body, content_type = _multipart(fields, path.name, blob, mime)

    # Accept a bare endpoint (…/v1) or the full path — don't double-append.
    base = settings.stt_base_url.rstrip("/")
    url = base if base.endswith("/audio/transcriptions") else f"{base}/audio/transcriptions"
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.stt_api_key}",
            "Content-Type": content_type,
            "User-Agent": _USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.stt_timeout_seconds) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise TranscriptionError(f"ASR request failed ({exc.code}): {detail}") from exc
    except Exception as exc:  # noqa: BLE001 - network, timeout, bad JSON
        raise TranscriptionError(f"ASR request failed: {exc}") from exc


def _parse_segments(body: dict, offset: float) -> list[Segment]:
    """Pull usable segments out of one response, rebased by ``offset``."""
    raw = body.get("segments")
    if not isinstance(raw, list):
        # Some providers answer without segments when the clip is tiny; the
        # flat `text` is still worth keeping as a single cue.
        text = str(body.get("text") or "").strip()
        return [Segment(offset, offset, text)] if text else []

    segments: list[Segment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        # Whisper narrates confidently over silence and music. Dropping these
        # is the difference between a transcript and a transcript with
        # invented dialogue in it.
        if float(item.get("no_speech_prob") or 0.0) > settings.stt_no_speech_threshold:
            continue
        start = float(item.get("start") or 0.0) + offset
        end = float(item.get("end") or 0.0) + offset
        segments.append(Segment(start, max(start, end), text))
    return segments


def _language_code(body: dict) -> str | None:
    """Normalise the reported language to an ISO-639-1 code where we can."""
    raw = str(body.get("language") or "").strip().lower()
    if not raw:
        return None
    return _LANGUAGE_CODES.get(raw, raw[:16])


def transcribe(source: Path, duration: float, work_dir: Path) -> Transcript:
    """Transcribe ``source``'s speech. Blocking — call from a worker thread.

    ``work_dir`` holds the extracted audio and its chunks; the caller owns it
    and is responsible for cleaning it up.

    Raises ``NoAudioTrack`` for a silent video and ``TranscriptionError`` for
    anything else that goes wrong.
    """
    if not settings.transcription_configured:
        raise TranscriptionError("No transcription endpoint configured")
    if not has_audio(source):
        raise NoAudioTrack(f"{source.name} has no audio track")

    audio = extract_audio(source, work_dir)
    chunks = _chunk_audio(audio, duration, work_dir)

    # Chunks are independent, so they go out concurrently — this is what keeps
    # a long recording near the wall-clock of its slowest single chunk.
    if len(chunks) == 1:
        bodies = [_transcribe_chunk(chunks[0][1])]
    else:
        workers = min(settings.stt_max_concurrency, len(chunks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            bodies = list(pool.map(lambda chunk: _transcribe_chunk(chunk[1]), chunks))

    segments: list[Segment] = []
    language: str | None = None
    for (offset, _), body in zip(chunks, bodies, strict=True):
        # The first chunk's detection is the one to trust: it is the only one
        # guaranteed to start on speech rather than mid-sentence.
        language = language or _language_code(body)
        segments.extend(_parse_segments(body, offset))

    segments.sort(key=lambda segment: segment.start)
    return Transcript(language=language, segments=segments)


def _vtt_timestamp(seconds: float) -> str:
    """Seconds → ``HH:MM:SS.mmm``, the only form WebVTT accepts for cues."""
    seconds = max(0.0, seconds)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    # Rounding .9996 up must carry, or the cue reads "…:03.1000".
    if millis == 1000:
        millis = 0
        secs += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def to_vtt(segments: list[Segment]) -> str:
    """Render segments as a WebVTT document the ``<track>`` element can load."""
    lines = ["WEBVTT", ""]
    for index, segment in enumerate(segments, start=1):
        # A zero-length cue never paints. Give the last-resort single-segment
        # case (a provider that returned only flat text) something visible.
        end = segment.end if segment.end > segment.start else segment.start + 2.0
        lines.append(str(index))
        lines.append(f"{_vtt_timestamp(segment.start)} --> {_vtt_timestamp(end)}")
        # "-->" inside cue text terminates the cue; nothing else needs escaping.
        lines.append(segment.text.replace("-->", "→"))
        lines.append("")
    return "\n".join(lines)
