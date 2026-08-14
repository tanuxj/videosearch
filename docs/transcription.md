# Transcription — subtitles and transcript

> **In one sentence:** while CLIP is still embedding frames, a much faster
> speech-to-text pass turns the audio into timed text, so the user is reading
> the transcript and seeing subtitles long before the video is searchable.

This is additive. Search is unchanged — still CLIP frames against a CLIP text
embedding, exactly as [updated-flow.md](updated-flow.md) describes. The
transcript is for *reading*, not for matching.

---

## 1. Why it runs in parallel

The two passes are wildly different in cost:

| Pass | An hour of video takes |
| ---- | ---------------------- |
| CLIP frame embedding (CPU) | minutes |
| Whisper-turbo on hosted inference | ~15–30 seconds |

Serialising them would hide the fast result behind the slow one. So
transcription is started as its own task the moment the file is probed, on its
own database session, and reports through its own status field.

That is why `Video` has **two** independent status columns:

```
status            : processing → ready | failed        (frame index)
transcript_status : pending → processing → ready | failed | skipped
```

A video sitting at `status="processing"` with `transcript_status="ready"` is
the normal, intended state — not a race. The frontend polls the library list
and fills the transcript panel in as soon as it flips.

`skipped` means *there will never be one*: the video has no audio track, or no
ASR endpoint is configured. A polling client uses it to stop waiting.

---

## 2. The pipeline

```
  Video file (already local, shared with the frame pass)
         │
         ▼
  ┌──────────────────┐   ffmpeg -vn -ac 1 -ar 16000
  │  Extract audio   │   an hour of video → a few MB
  └──────────────────┘
         │
         ▼
  ┌──────────────────┐   explicit -ss per chunk, so each
  │  Split into      │   offset is exact rather than "wherever
  │  N-minute chunks │   the cut happened to land"
  └──────────────────┘
         │ chunks upload concurrently
         ▼
  ┌──────────────────┐   POST /audio/transcriptions
  │  ASR endpoint    │   response_format=verbose_json
  └──────────────────┘   → segments + detected language
         │
         ▼
  Rebase each chunk's times by its offset → one timeline
         │
         ▼
  transcript_segments  (video_id, idx, start_sec, end_sec, text)
         │
         ├──────────────► GET /transcript      → clickable transcript panel
         └──────────────► GET /captions.vtt    → <track> subtitles
```

Audio is extracted at mono 16 kHz because that is what Whisper resamples to
internally — sending anything richer is upload time spent for nothing.

Chunking exists for two reasons, not one: it keeps every request under the
provider's file-size cap (Groq: 25 MB), and it lets a long recording finish in
roughly the wall-clock of its slowest chunk instead of the sum of all of them.

---

## 3. Choosing a provider

Any OpenAI-compatible `/audio/transcriptions` endpoint works. The default is
Groq, chosen on speed-per-dollar:

| Provider | 1 hr video | Lang detect | Timestamps | ~Cost/hr |
| -------- | ---------- | ----------- | ---------- | -------- |
| **Groq** `whisper-large-v3-turbo` | ~15–30 s | yes | segment + word | ~$0.04 |
| Deepgram Nova-3 | ~30–60 s | yes | word-level, best-in-class | ~$0.26 |
| AssemblyAI Universal | ~1–2 min | yes | word + speaker labels | ~$0.15–0.27 |
| OpenAI `whisper-1` | ~2–4 min | yes | segment | ~$0.36 |

Switch with `STT_BASE_URL` + `STT_MODEL`. Deepgram is worth the money if you
later need real-time streaming captions or speaker diarization; Groq is the
right default for "show me the text, now".

---

## 4. Two things worth knowing

**Language detection reads the opening audio only.** A video that switches
language partway through is still labelled by how it starts. If that matters,
Amazon Transcribe offers per-utterance multi-language identification — at the
cost of a job-queue architecture that is minutes slower to first result.

**Whisper narrates over silence.** Left alone it will confidently transcribe
music and room tone into plausible dialogue ("Thanks for watching!").
Segments whose reported no-speech probability exceeds
`STT_NO_SPEECH_THRESHOLD` are dropped for exactly this reason.

---

## 5. What this unlocks next

`transcript_segments` is already the right shape for keyword or semantic
search over what was *said*, which the visual-only design fundamentally cannot
do — "the part where they mention pricing" is invisible to CLIP. Adding a
`tsvector` column with a GIN index, or embedding the segments, would make
spoken content searchable alongside the frames. Deliberately not built yet:
this pass is about making the text **visible**, not about changing search.
