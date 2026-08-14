"""Unit tests for the speech-to-text module.

The ASR HTTP call is always mocked — these must never hit the network. The
ffmpeg paths are exercised for real against a generated fixture clip, since
"does the bundled binary actually carry this encoder" is exactly the kind of
assumption a mock would hide.
"""

import json
import subprocess
import urllib.error
import urllib.request

import pytest

from app.core.config import get_settings
from app.videos import transcribe
from app.videos.clips import ffmpeg_binary


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:  # pragma: no cover - trivial
        return False

    def read(self) -> bytes:
        return self._body


def _enable_stt(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "stt_api_key", "gsk-test")


def _body(segments: list[dict], language: str = "english") -> bytes:
    return json.dumps({"language": language, "text": "…", "segments": segments}).encode()


def _segment(start: float, end: float, text: str, no_speech: float = 0.0) -> dict:
    return {"start": start, "end": end, "text": text, "no_speech_prob": no_speech}


@pytest.fixture(scope="module")
def clip_with_audio(tmp_path_factory):
    """A 25-second test pattern with a 440 Hz tone on the audio track."""
    path = tmp_path_factory.mktemp("transcribe") / "with-audio.mp4"
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
            "testsrc=size=160x120:rate=10:duration=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=25",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture(scope="module")
def clip_without_audio(tmp_path_factory):
    path = tmp_path_factory.mktemp("transcribe") / "silent.mp4"
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
            "testsrc=size=160x120:rate=10:duration=3",
            "-c:v",
            "libx264",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


# ── WebVTT rendering ────────────────────────────────────────


def test_vtt_has_header_and_numbered_cues() -> None:
    vtt = transcribe.to_vtt(
        [transcribe.Segment(0.0, 3.4, "Hello"), transcribe.Segment(3.4, 6.0, "there")]
    )
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:03.400" in vtt
    assert "00:00:03.400 --> 00:00:06.000" in vtt
    assert "\n1\n" in vtt and "\n2\n" in vtt


def test_vtt_timestamp_rounding_carries() -> None:
    # .9996 rounds to 1000ms, which must carry into the seconds field rather
    # than render the impossible "…:07.1000".
    assert transcribe._vtt_timestamp(7.9996) == "00:00:08.000"
    assert transcribe._vtt_timestamp(3661.9996) == "01:01:02.000"
    assert transcribe._vtt_timestamp(-5.0) == "00:00:00.000"


def test_vtt_escapes_arrow_in_cue_text() -> None:
    # A literal "-->" inside cue text would terminate the cue early.
    vtt = transcribe.to_vtt([transcribe.Segment(0.0, 1.0, "left --> right")])
    assert "left --> right" not in vtt
    assert "left → right" in vtt


def test_vtt_gives_zero_length_cue_a_visible_duration() -> None:
    vtt = transcribe.to_vtt([transcribe.Segment(9.0, 9.0, "flat")])
    assert "00:00:09.000 --> 00:00:11.000" in vtt


def test_vtt_of_nothing_is_still_a_valid_document() -> None:
    assert transcribe.to_vtt([]).strip() == "WEBVTT"


# ── Response parsing ────────────────────────────────────────


def test_segments_are_rebased_by_chunk_offset() -> None:
    parsed = transcribe._parse_segments({"segments": [_segment(1.0, 4.0, "later")]}, offset=600.0)
    assert (parsed[0].start, parsed[0].end) == (601.0, 604.0)


def test_high_no_speech_segments_are_dropped() -> None:
    monkeypatched = get_settings().stt_no_speech_threshold
    parsed = transcribe._parse_segments(
        {
            "segments": [
                _segment(0.0, 1.0, "real speech", no_speech=0.05),
                _segment(1.0, 2.0, "Thanks for watching!", no_speech=monkeypatched + 0.2),
            ]
        },
        offset=0.0,
    )
    assert [item.text for item in parsed] == ["real speech"]


def test_empty_segment_text_is_dropped() -> None:
    parsed = transcribe._parse_segments(
        {"segments": [_segment(0.0, 1.0, "   "), _segment(1.0, 2.0, "kept")]}, offset=0.0
    )
    assert [item.text for item in parsed] == ["kept"]


def test_flat_text_response_becomes_one_segment() -> None:
    # Some providers omit `segments` on a very short clip.
    parsed = transcribe._parse_segments({"text": "just this"}, offset=12.0)
    assert len(parsed) == 1
    assert parsed[0].text == "just this"
    assert parsed[0].start == 12.0


def test_language_name_maps_to_iso_code() -> None:
    assert transcribe._language_code({"language": "English"}) == "en"
    assert transcribe._language_code({"language": "hindi"}) == "hi"
    # Unknown languages pass through rather than being dropped.
    assert transcribe._language_code({"language": "klingon"}) == "klingon"
    assert transcribe._language_code({}) is None


# ── Multipart encoding ──────────────────────────────────────


def test_multipart_body_carries_fields_and_file() -> None:
    body, content_type = _multipart_call()
    assert content_type.startswith("multipart/form-data; boundary=----videosearch")
    assert b'name="model"' in body
    assert b"whisper-test" in body
    assert b'name="file"; filename="audio.ogg"' in body
    assert b"RAWBYTES" in body
    boundary = content_type.split("boundary=")[1]
    assert body.endswith(f"--{boundary}--\r\n".encode())


def _multipart_call():
    return transcribe._multipart({"model": "whisper-test"}, "audio.ogg", b"RAWBYTES", "audio/ogg")


# ── ffmpeg paths (real binary, generated fixtures) ──────────


def test_has_audio_detects_both_ways(clip_with_audio, clip_without_audio) -> None:
    assert transcribe.has_audio(clip_with_audio) is True
    assert transcribe.has_audio(clip_without_audio) is False


def test_extract_audio_produces_a_small_mono_file(clip_with_audio, tmp_path) -> None:
    out = transcribe.extract_audio(clip_with_audio, tmp_path)
    assert out.exists() and out.stat().st_size > 0
    # Audio-only must be far smaller than the source it came from — that size
    # difference is the whole reason the upload is quick.
    assert out.stat().st_size < clip_with_audio.stat().st_size


def test_short_audio_is_not_chunked(clip_with_audio, tmp_path) -> None:
    audio = transcribe.extract_audio(clip_with_audio, tmp_path)
    chunks = transcribe._chunk_audio(audio, duration=25.0, out_dir=tmp_path)
    assert chunks == [(0.0, audio)]


def test_long_audio_splits_at_exact_offsets(clip_with_audio, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "stt_chunk_seconds", 10.0)
    audio = transcribe.extract_audio(clip_with_audio, tmp_path)
    chunks = transcribe._chunk_audio(audio, duration=25.0, out_dir=tmp_path)

    # Offsets are what the segment timestamps get rebased by, so they have to
    # be exactly the values requested — not "wherever the cut landed".
    assert [offset for offset, _ in chunks] == [0.0, 10.0, 20.0]
    assert all(path.exists() and path.stat().st_size > 0 for _, path in chunks)


# ── End to end, with the network stubbed ────────────────────


def test_transcribe_stitches_chunks_onto_one_timeline(
    clip_with_audio, tmp_path, monkeypatch
) -> None:
    _enable_stt(monkeypatch)
    monkeypatch.setattr(get_settings(), "stt_chunk_seconds", 10.0)
    # Every chunk reports times from its own zero; the module must rebase them.
    monkeypatch.setattr(
        transcribe,
        "_transcribe_chunk",
        lambda path: json.loads(_body([_segment(1.0, 2.0, "line")])),
    )

    result = transcribe.transcribe(clip_with_audio, duration=25.0, work_dir=tmp_path)

    assert result.language == "en"
    assert [round(item.start, 3) for item in result.segments] == [1.0, 11.0, 21.0]


def test_transcribe_rejects_a_silent_video(clip_without_audio, tmp_path, monkeypatch) -> None:
    _enable_stt(monkeypatch)
    with pytest.raises(transcribe.NoAudioTrack):
        transcribe.transcribe(clip_without_audio, duration=3.0, work_dir=tmp_path)


def test_transcribe_without_a_key_is_an_error(clip_with_audio, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "stt_api_key", None)
    with pytest.raises(transcribe.TranscriptionError):
        transcribe.transcribe(clip_with_audio, duration=25.0, work_dir=tmp_path)


def test_http_error_surfaces_the_provider_message(tmp_path, monkeypatch) -> None:
    _enable_stt(monkeypatch)
    audio = tmp_path / "audio.ogg"
    audio.write_bytes(b"not really audio")

    def boom(*a, **k):
        raise urllib.error.HTTPError(
            "url", 413, "Payload Too Large", {}, __import__("io").BytesIO(b"file too big")
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(transcribe.TranscriptionError, match="413"):
        transcribe._transcribe_chunk(audio)


def test_language_hint_is_sent_when_configured(tmp_path, monkeypatch) -> None:
    _enable_stt(monkeypatch)
    monkeypatch.setattr(get_settings(), "stt_language", "hi")
    audio = tmp_path / "audio.ogg"
    audio.write_bytes(b"bytes")

    sent: dict = {}

    def capture(request, *a, **k):
        sent["body"] = request.data
        sent["url"] = request.full_url
        return _FakeResponse(_body([]))

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    transcribe._transcribe_chunk(audio)

    assert sent["url"].endswith("/audio/transcriptions")
    assert b'name="language"' in sent["body"]
    assert b"verbose_json" in sent["body"]
