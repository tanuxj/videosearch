# Updated Flow — Visual-Only Semantic Video Search

> **Superseded in part.** Sections 2 and 5 below say there is no audio
> pipeline. That was true when this was written and is no longer: an optional
> transcription pass now runs *in parallel* with frame embedding, producing
> subtitles and a clickable transcript. It does not touch search — matching is
> still CLIP-only, exactly as described here. See
> [transcription.md](transcription.md).

> **The whole pipeline in one sentence:** upload → pull frames out at regular
> intervals → turn each frame into a vector with CLIP → save vectors with
> timestamps → when the user describes a scene in text, turn that into a vector
> too and find the closest-matching frame → jump the video player there.

---

## 1. How the flow changes

| Step | What happens |
| ---- | ------------ |
| **1 — Video uploaded** | User uploads the video file to the backend, same as before. No audio processing needed at all now. |
| **2 — Extract frames** | The backend extracts frames from the video at regular intervals — say, one frame every 1–2 seconds. Each frame is just an image, tagged with its timestamp. |
| **3 — Embed each frame** | Each extracted frame (image) is run through CLIP's image encoder, which converts it into a vector — a set of numbers representing what's visually in that frame. |
| **4 — Store frame vectors** | Each frame's vector is saved into Postgres (**pgvector**), along with the exact timestamp that frame came from. |
| **5 — User describes a scene** | User types a description like *"a red car driving on a highway"*. This text is run through CLIP's text encoder — the same shared space as the image vectors. |
| **6 — Find closest frames** | Postgres compares the text vector against every stored frame vector and returns the frames whose visual content is closest in meaning to the description. |
| **7 — Jump to the scene** | The best matching frame's timestamp is sent to the frontend, which jumps the video player to that exact moment so the user sees the scene. |

---

## 2. What this simplifies for you

- **No Whisper, no audio processing, no transcription at all.**
- The **chunks table** becomes a **frames table** instead:
  `id`, `video_id`, `timestamp`, `embedding` — no `transcript_text` column needed.
- The whole pipeline is just:
  `upload → extract frames → embed frames with CLIP → store → compare user's text
  description against frames → return matching timestamp`.

**Net result:** you're down to **one model (CLIP)** instead of two, and **one type
of embedding** instead of a text + visual fusion.

---

## 3. One practical detail worth knowing

Extracting a frame every 1 second means a **10-minute video gives ~600 frames** —
very manageable at MVP scale.

For longer videos later:

- space extraction out more (every 2–3 seconds), **or**
- use **scene-change detection** to only grab frames when the visual content
  actually shifts.

For now, **fixed-interval extraction is the simplest and totally fine.**

---

## 4. Architecture at a glance

```
  User uploads video
         │
         ▼
  ┌───────────────┐     every 1–2s     ┌──────────────────┐
  │  Frame grab   │ ─────────────────► │  Frame + timestamp │
  └───────────────┘                    └──────────────────┘
                                              │ CLIP image encoder
                                              ▼
                                      embedding vector
                                              │
                                              ▼
                              Postgres + pgvector (frames table)
                                              ▲
                                              │ text vector (CLIP text encoder)
  User types "a red car on a highway" ────────┘
         │
         ▼
   Top matching frame → timestamp
         │
         ▼
   Video player seeks to that moment
```

---

## 5. Stack summary

- **One model:** CLIP (image encoder for frames, text encoder for queries)
- **One database:** Postgres + pgvector
- **No audio pipeline anywhere:** no Whisper, no transcription, no text/visual fusion
