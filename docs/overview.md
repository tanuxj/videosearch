# Semantic Video Search App — Architecture & Build Plan

## Overview

A full-stack app where users upload a video (or paste a URL), and can later
search it with a natural-language prompt (e.g. "the scene where the car
crashes") to jump straight to the matching moment, with timestamps.

**Stack**: FastAPI (backend) + TypeScript/React (frontend), with a background
processing pipeline and a vector database for semantic search.

---

## 1. Ingestion

- **Direct upload**: stream large files to object storage (S3, or local disk
  for MVP) via a FastAPI endpoint. Use chunked/multipart upload for big files.
- **URL input**: use `yt-dlp` server-side to download the video, then treat it
  identically to an uploaded file.
- As soon as a video lands in storage, kick off a background job — don't
  block the HTTP request. Use Celery or RQ with Redis for a real queue, or
  FastAPI's `BackgroundTasks` for a quick MVP.

## 2. Processing pipeline (core of the project)

Runs asynchronously per uploaded video:

1. **Scene detection** — `PySceneDetect` splits the video into shots/scenes
   based on visual cuts, giving rough time boundaries.
2. **Visual embeddings** — extract 1–2 keyframes per scene and embed them
   with CLIP, so visual concepts ("a red car," "person running") are
   searchable even if nobody says those words aloud.
3. **Fuse** — merge transcript segments and scene boundaries into "chunks,"
   each with `start_time`, `end_time`, transcript text, and a visual +
   text embedding.

## 3. Storage layer

- **Vector DB**: Qdrant, Weaviate, or `pgvector` inside Postgres if you want
  a single database. Stores embeddings + metadata (`video_id`, `start`,
  `end`, transcript snippet).
- **Relational DB**: Postgres for video metadata, processing status, and
  user accounts.

## 4. Search

- User's prompt → embed with the same text encoder (and optionally CLIP's
  text encoder for visual matching) → vector similarity search → top-k
  chunks returned with timestamps.
- If combining text + visual scores, a simple weighted sum of both
  similarities is a solid first pass.
- Response shape: `{ video_id, start_time, end_time, thumbnail, matched_text }`
  so the frontend can jump straight there.

## 5. Frontend (TypeScript)

- Next.js/React with a video player (`<video>` + custom controls, or
  `react-player`) supporting `player.currentTime = timestamp` seeking.
- Upload UI with a progress bar; poll a `/status/{job_id}` endpoint or use
  WebSockets to notify the user when processing finishes.
- Search box hitting `/search?video_id=...&query=...`, rendering clickable
  result cards (thumbnail + timestamp) that seek the player.

---

## Architecture flow

```
Upload / paste URL  --->  Object storage (S3 / local)
                                  |  (async job)
                                  v
        ┌────────────────────────────────────────────┐
        │        Processing pipeline (worker)          │
        │                                              │
        │  Scene detection   Transcription   Frame      │
        │  (PySceneDetect)   (Whisper)       embeddings │
        │        \               |              /       │
        │         v              v             v        │
        │       Chunk + tag with time ranges            │
        └────────────────────────────────────────────┘
                                  |
                                  v
                        Vector DB (Qdrant / pgvector)
                                  |
                                  v
                        Search API (embed prompt,
                          similarity search)
                                  |
                                  v
                Video player (seeks to matched timestamp)
```

---

## Suggested build order

1. **MVP**: upload → store → transcribe with Whisper → text-only semantic
   search over transcript chunks → seek video on click. Skip visual
   embeddings initially.
2. Add scene detection for cleaner "scene" boundaries instead of arbitrary
   transcript chunks.
3. Add CLIP visual embeddings so silent/visual scenes are searchable too.
4. Add an async job queue + status polling/websockets for smoother UX with
   large videos.
5. Add URL ingestion via `yt-dlp`.

## Things to watch out for

- **Processing time**: a 1-hour video can take a while for Whisper + CLIP on
  CPU — plan for GPU workers at scale, or accept slower turnaround for MVP.
- **Chunk granularity**: too fine and search returns disjointed micro-clips;
  too coarse and you lose precision. Scene-based chunks (a few seconds to
  ~1 minute) are usually the sweet spot.
- **Storage cost**: large videos add up fast — consider transcoding to a
  compressed format after upload.