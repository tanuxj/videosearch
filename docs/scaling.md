# Scaling the VideoSearch App — Infrastructure Plan

> Status: planning doc. The app currently runs as a **single machine that does
> everything**: FastAPI + in-process indexing jobs + the CLIP model + Postgres.
> This document is the roadmap for taking it from "works on my machine" to a
> real, hosted product — in phases, with costs, and with the exact files that
> need to change.

---

## 0. Where we are today

```
Browser (React/Vite, :5174)
   │  VITE_API_URL=http://127.0.0.1:3006
   ▼
FastAPI + uvicorn (:3006)  ──── the ONE machine
   ├── auth      JWT access + rotating httpOnly refresh cookie
   ├── videos    upload / list / status / stream / delete
   ├── pipeline  BackgroundTasks: OpenCV extract → CLIP embed → pgvector
   ├── search    POST /search/clips  (CLIP text → pgvector `<=>`)
   └── embedder  ~600 MB CLIP model, lazy-loaded in-process
        │
        ├── Postgres (pgvector, HNSW index)
        └── Cloudflare R2  (or local disk fallback)
```

**Already future-proof:** objects live in **R2** (cloud) and search is
**pgvector** in Postgres — both scale with managed services rather than
requiring a rewrite.

### Current limits (enforced in code)

| Limit | Value | Where |
|---|---|---|
| Upload size | 10 GiB default (413, configurable) | `MAX_UPLOAD_BYTES` in `videos/service.py` |
| Large-file path | >5 GiB → presigned multipart to R2 | `POST /videos/presign/multipart` |
| File types | .mp4 .mov .webm .mkv .avi .m4v (415) | `ALLOWED_EXTENSIONS` |
| Search results | 1–50 (`limit`) | `videos/search.py` |
| Prompt length | ≤ 300 chars | `videos/search.py` |
| UI indexing wait | ~5 min poll cap | `UploadDialog.tsx` |

**Not limited:** number of videos, duration, frames per video.
**Real ceilings:** R2 free tier (10 GB), CPU indexing speed (~1× realtime), RAM.

---

## 1. What breaks at scale

| Bottleneck | Why it breaks | Fix |
|---|---|---|
| **Indexing jobs** | `BackgroundTasks` run inside the API process. Restart → job dies. Multiple workers → multiple 600 MB model copies. No retries/queue. | Extract to a job queue + separate worker |
| **CPU inference** | CLIP on CPU ≈ real-time. 10 concurrent uploads slow the whole API. | GPU worker (serverless) |
| **Uploads through the API** | FastAPI buffers the whole multipart body in RAM (see `service.py` note). Large files × N = OOM. | Presigned URLs → browser uploads straight to R2 (multipart chunks past 5 GiB) |
| **Playback through the API** | Every byte-range request proxies through the API → egress + CPU. | Presigned GET + CDN on the bucket |
| **Single Postgres** | Contention between writes (indexing) and reads (search/stream auth). | Managed Postgres, later read replicas |

---

## 2. Target architecture (after Phase 2)

```
Browser (Vercel / Cloudflare Pages)
   │  presigned PUT ──────────────►  Cloudflare R2 (+ CDN for playback)
   │                                    ▲
   │  API: presigned URL, status, search │ job messages
   ▼                                    │
FastAPI (Render / Fly.io)        ┌──────┴──────┐
   │  auth / CRUD / search       │   Queue     │  Redis (ARQ) or Hatchet
   │                             │  (jobs)     │
   ▼                             └──────┬──────┘
Neon Postgres (pgvector)                ▼
                              GPU worker (RunPod / Modal)
                               OpenCV extract → CLIP embed
                               → writes embeddings back to Postgres
```

**Key idea:** the API never touches video bytes or the model again. It mints
URLs, answers queries, and enqueues work.

---

## 3. Phase 1 — Launch (dozens of users, ~$0–10/mo)

Goal: everything in the cloud, decoupled, no single-process fragility.
Config + a few code edits — not a rewrite.

### Infra to provision

| Piece | Service | Notes |
|---|---|---|
| Frontend | **Vercel** or **Cloudflare Pages** | Static Vite build as-is; set `VITE_API_URL` to the API domain. Vercel is frontend-only — not for the backend. |
| API | **Render** (Docker web service), **Fly.io**, or **Google Cloud Run** | Always-on FastAPI container from the existing `Dockerfile`; healthcheck on `/api/v1/health` (already exists); env vars in dashboard. |
| Database | **Neon** (serverless Postgres, pgvector built in) | **Zero code changes**: same asyncpg + SQLAlchemy + `DATABASE_URL`. Run `alembic upgrade head` against it. |
| Objects | **R2** (already using) + **Cloudflare CDN on the bucket** | Free egress to Cloudflare's network; playback from the edge. |

### Code changes

1. **`videos/storage.py` + `videos/routes.py`** — presigned URLs:
   - Upload: `POST /videos` returns `{video_id, upload_url}` (R2
     `generate_presigned_url('put_object')`); browser PUTs the file
     directly. No API RAM spent.
   - Playback: return a short-lived presigned `GET` instead of proxying
     bytes. Frontend `fetch(presignedUrl)` is nearly a drop-in for
     `streamSourceFor()`.
2. **`videos/pipeline.py`** — replace `background_tasks.add_task(...)`
   (in `routes.py`) with **enqueue a job message**. Pipeline body stays
   identical; only the trigger changes.
3. **`main.py` / `cli.py`** — uvicorn multi-worker config + graceful
   shutdown draining in-flight jobs.
4. **Frontend `lib/store.ts`** — upload via presigned URL; status polling
   unchanged.

### Queue choice

| Option | Fit |
|---|---|
| **Redis + ARQ** | Lightweight, async-native, matches the codebase's async style. Best default. |
| **Hatchet** | Open-source Python task queue with retries/DAGs. Good when jobs get complex. |
| Zeplo / Cloudflare Queues | Managed, but aimed at HTTP/Worker-style jobs — a Python worker pool is the natural fit here. |

---

## 4. Phase 2 — Production (hundreds–thousands of users, ~$50–200/mo)

### Infra to add

| Piece | Service | Notes |
|---|---|---|
| **GPU worker** | **RunPod** (serverless GPU) or **Modal** | Job pulls video from R2, OpenCV + CLIP on GPU (10–50× faster than CPU), writes embeddings back. `pipeline.py` moves here almost unchanged. |
| **Redis** | Upstash (managed) or Render's built-in | Queue + cache. |
| **Auth hardening** | Rate limiting on `/auth/login` + uploads; cron to prune expired `refresh_tokens` (they accumulate forever today); optional email verification. | |
| **Observability** | Sentry for errors; **Healthchecks.io** pings `/api/v1/health`; structured logs to a sink. | |

### Code changes

1. **`videos/embedder.py`** — behind an interface: `LocalEmbedder` vs
   `RemoteEmbedder(HTTP)`. Tests keep mocking it, so nothing downstream
   changes.
2. **`videos/pipeline.py`** — becomes the worker entrypoint
   (`python -m app.videos.worker`): pull job → `storage.get_local_path`
   (already exists for R2!) → embed on GPU → `SessionFactory` writes
   (already isolated per job).
3. **`videos/search.py`** — pgvector HNSW tuning (`ef_search`, `m`) past
   ~1M rows; optional Redis query cache.
4. **New** — quotas + billing hooks (the "first 5 videos" copy on the Home
   page is currently unenforced), per-user rate limits.
5. **`Dockerfile`** — drop torch/sentence-transformers from the API image
   (model moves to the GPU worker) → image shrinks from ~2 GB to ~200 MB.

---

## 5. Phase 3 — Large scale (only if it gets there)

- Multiple API regions (Fly.io machines per region) + DB read replicas.
- Vector partitioning — partition `frames` by `owner_id` or time; or move
  hot embeddings to a purpose-built vector DB (**Qdrant**) while Postgres
  stays the system of record.
- Transcoding + adaptive bitrate via **api.video** or **Cloudflare Stream**.
  Note: search runs on the original file — transcoding is purely a playback
  concern.
- Zero-downtime migrations (expand-only patterns).

---

## 6. Cost reality

| Phase | What you pay for | Rough cost |
|---|---|---|
| **1** | Render (small), Neon free tier, R2 free tier, Vercel free | **$0–10/mo** |
| **2** | GPU worker (RunPod ~$0.30–0.79/GPU-hr, only when indexing), Redis, Neon scale, monitoring | **$50–200/mo** |
| **3** | Multi-region + vector DB | $500+/mo — by then there's revenue |

The current single box is genuinely fine until there are real concurrent
users. The **first move that matters** is Phase 1's decoupling (presigned
uploads + a queue + managed Postgres), because that's what makes everything
after it possible without rewrites.

---

## 7. Suggested implementation order (Phase 1)

1. Provision Neon → point `DATABASE_URL` at it → `alembic upgrade head`.
2. Add presigned upload/playback to `storage.py` + routes.
3. Extract the pipeline trigger behind a queue interface (Redis/ARQ).
4. Add a Redis + worker service to the compose file / deploy config.
5. Deploy API (Render/Fly) + frontend (Vercel/Pages), set `VITE_API_URL`.
6. Swap R2 bucket to Cloudflare CDN-enabled.

---

## Appendix — current file map (what each file does)

```
videosearchbackend/
├── app/
│   ├── main.py            # FastAPI app, CORS, router registration, lifespan
│   ├── cli.py             # `uv run videosearch-api [--reload]`
│   ├── core/config.py     # pydantic-settings; JWT, R2, pipeline knobs
│   ├── db/                # async engine, session factory, Alembic import point
│   ├── auth/              # signup/login/refresh/logout; JWT + rotating cookies
│   └── videos/
│       ├── routes.py      # upload/list/status/stream/delete (BackgroundTasks here)
│       ├── service.py     # business logic; upload cap, extension allowlist
│       ├── storage.py     # R2/local facade; presigned/stream hooks go here
│       ├── pipeline.py    # 1 fps extract → CLIP embed → pgvector insert
│       ├── embedder.py    # lazy CLIP singleton (image + text)
│       └── search.py      # POST /search/clips  (pgvector `<=>`)
videosearchfrontend/
└── src/
    ├── lib/store.ts       # API-aware library: list/upload/get/delete/stream blob
    ├── lib/http.ts        # fetch wrapper + token refresh
    └── lib/api.ts         # searchClips → backend CLIP search
```
