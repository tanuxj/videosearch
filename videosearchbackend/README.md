# VideoSearch backend

Production-ready **FastAPI** template, managed with **uv**. Serves the video
search API on **port 3006**.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.12 is pinned via `.python-version`)

## Quick start

```bash
uv sync                 # create .venv + install deps (generates uv.lock)
uv run videosearch-api --reload   # run on HOST/PORT from .env (default :3006)
```

Or run uvicorn directly:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 3006 --reload
```

Open:

- API docs (Swagger UI): http://127.0.0.1:3006/docs
- Health check: http://127.0.0.1:3006/api/v1/health
- Search: http://127.0.0.1:3006/api/v1/search?q=typescript

## Scripts

```bash
uv run pytest                # run the test suite
uv run ruff check .          # lint
uv run ruff format .         # format
uv lock --check              # verify uv.lock is up to date
```

## Configuration

Settings are loaded from `.env` (see `.env.example`) via pydantic-settings in
`app/core/config.py`:

| Variable        | Default                                     | Purpose                       |
| --------------- | ------------------------------------------- | ----------------------------- |
| `APP_NAME`      | `VideoSearch API`                           | Shown in docs / responses     |
| `APP_ENV`       | `development`                               | `development` / `test` / `production` |
| `APP_DEBUG`     | `false`                                     | Debug mode                    |
| `HOST`          | `127.0.0.1`                                 | Bind address (used by `videosearch-api`) |
| `PORT`          | `3006`                                      | Bind port (used by `videosearch-api`)    |
| `CORS_ORIGINS`  | `["http://localhost:5174","http://127.0.0.1:5174"]` | Browser origins allowed to call the API |
| `LOG_LEVEL`     | `INFO`                                      | Root log level                |
| `DATABASE_URL`  | `postgresql://videosearch:videosearch@localhost:5432/videosearch` | Postgres connection string |
| `POSTGRES_HOST` | `localhost`                                 | Postgres host (set to `db` inside docker-compose) |
| `POSTGRES_PORT` | `5432`                                      | Postgres port                |
| `POSTGRES_DB`   | `videosearch`                               | Postgres database name       |
| `POSTGRES_USER` | `videosearch`                               | Postgres user                |
| `POSTGRES_PASSWORD` | `videosearch`                          | Postgres password (override in `.env`!) |
| `URL_IMPORT_ENABLED` | `true`                                     | Allow indexing videos from pasted URLs |
| `URL_IMPORT_MAX_BYTES` | `10737418240` (10 GiB)              | Cap on a URL-downloaded video |
| `URL_IMPORT_FORMAT` | `b[ext=mp4]/b`                           | yt-dlp format preference (progressive MP4 first) |
| `URL_IMPORT_ALLOW_PRIVATE` | `false`                         | SSRF guard — set `true` to allow private/local hosts (tests only!) |
| `URL_IMPORT_MAX_BATCH` | `50`                                  | Most videos one batch import reserves, after playlist/channel expansion |
| `URL_IMPORT_EXPAND_PLAYLISTS` | `false`                     | Expand a pasted playlist/channel link into its videos (off: such links are rejected) |
| `STT_API_KEY`   | _(unset)_                                   | ASR key. **Transcription is off until this is set.** |
| `STT_BASE_URL`  | `https://api.groq.com/openai/v1`            | Any OpenAI-compatible `/audio/transcriptions` endpoint |
| `STT_MODEL`     | `whisper-large-v3-turbo`                    | ASR model id |
| `STT_LANGUAGE`  | _(unset)_                                   | ISO-639-1 hint; unset means auto-detect |
| `STT_CHUNK_SECONDS` | `600`                                   | Audio is split into chunks this long before upload |
| `STT_MAX_CONCURRENCY` | `4`                                   | Chunks transcribed in parallel |
| `STT_NO_SPEECH_THRESHOLD` | `0.6`                             | Drop segments the model flags as probably-not-speech |

## Transcription (subtitles + transcript)

Set `STT_API_KEY` and every indexed video also gets timed text: WebVTT
subtitles on the player and a clickable transcript. Language is detected
automatically unless `STT_LANGUAGE` pins it.

The default endpoint is [Groq](https://console.groq.com/keys) —
`whisper-large-v3-turbo` transcribes an hour of audio in well under a minute
at roughly $0.04/hr. Any OpenAI-compatible endpoint works; for OpenAI itself
set `STT_BASE_URL=https://api.openai.com/v1` and `STT_MODEL=whisper-1`.

**Transcription runs alongside frame embedding, not after it.** Speech
recognition takes seconds where CLIP takes minutes, so a video is routinely
`status="processing"` with `transcript_status="ready"` — that gap is the
point. The transcript is readable while the indexing bar is still moving.

How it works (`app/videos/transcribe.py`):

1. ffmpeg (bundled by imageio-ffmpeg — no system install) extracts a mono
   16 kHz audio stream. An hour of video becomes a few MB, since Whisper
   resamples to that anyway.
2. Audio is split into `STT_CHUNK_SECONDS` pieces, each cut with an explicit
   `-ss` so its offset is exact. Chunks upload concurrently, keeping a long
   recording near the wall-clock of its slowest chunk.
3. Segments are stitched onto one timeline and written to
   `transcript_segments`.

Endpoints:

| Route | Returns |
| ----- | ------- |
| `GET /api/v1/videos/{id}/transcript` | JSON segments + detected language + status |
| `GET /api/v1/videos/{id}/captions.vtt` | WebVTT for a `<track>` element |

`transcript_status` is `pending` → `processing` → `ready` / `failed`, or
`skipped` when the video has no audio track or no key is configured — so a
polling client knows when to stop.

Videos with no audio are `skipped`, not `failed`: a silent upload is a normal
thing, not an error. Transcription failure never fails indexing.

## URL import (paste-a-link)

Users can index videos from pasted links instead of uploading files:

| Method | Route                   | Auth | Purpose                                        |
| ------ | ----------------------- | ---- | ---------------------------------------------- |
| POST   | `/api/v1/videos/from-url` | bearer | Validate the URL, reserve a `processing` video, and start the background download + index |
| POST   | `/api/v1/videos/from-urls` | bearer | Same, for many links at once — playlists/channels expand into their videos, failures reported per URL |
| GET    | `/api/v1/videos/{id}/clips` | bearer | List the video's auto-extracted (saved) clips |
| DELETE | `/api/v1/videos/{id}/clips/{clip_id}` | bearer | Delete one saved clip |

`POST /api/v1/videos/from-url` with `{"url": "https://…"}` (optionally
`{"url": …, "prompt": "a red car", "clip_limit": 3}`):

1. Validates the link — `http(s)` only, and the host must resolve to a
   **public** address (SSRF guard; `URL_IMPORT_ALLOW_PRIVATE=true` lifts it
   for tests).
2. Probes it with **yt-dlp** (YouTube, Twitch, Zoom, Vimeo, …) or a plain
   HTTP probe for direct file URLs — rejecting live streams, audio-only
   links, and anything over the size cap.
3. Reserves a `processing` video row, then downloads the video in the
   background (yt-dlp first, direct HTTP fallback), stores it in the same
   storage as uploads, and runs the normal indexing pipeline — so streaming,
   clip downloads and scene search all work exactly like an uploaded file.
4. When `prompt` is set, the job runs the same CLIP search the search page
   uses once indexing finishes and **auto-saves the best `clip_limit` scenes**
   as clips (`GET /videos/{id}/clips`) — the library shows highlights without
   a manual search.

`POST /api/v1/videos/from-urls` with `{"urls": ["https://…", …]}` imports
many videos at once. Every link is validated + probed individually — a bad
link reports its own error instead of failing the batch, and duplicates
within the request are skipped. A shared `prompt` auto-saves matching clips
on every imported video.

Playlist/channel expansion is **off by default**: pasting a channel or
playlist link is rejected with a clear message rather than importing tens of
videos from one paste. Set `URL_IMPORT_EXPAND_PLAYLISTS=true` to expand such
links into their individual videos (capped at `URL_IMPORT_MAX_BATCH`).

Caveats: downloading YouTube videos can violate their ToS and some videos
are throttled/geo-blocked; Zoom recordings usually require login; live
streams have no end point and can't be indexed. The backend needs outbound
internet access.

> `CORS_ORIGINS` already allows the Vite frontend (port 5174) — no extra setup
> needed to call this API from the browser.

## Search history

Every search the user runs is recorded so the frontend's **History** tab can
list past searches, replay their clips, and re-run them:

| Method | Route                  | Auth   | Purpose                                        |
| ------ | ---------------------- | ------ | ---------------------------------------------- |
| GET    | `/api/v1/history`      | bearer | List my past searches, newest first            |
| POST   | `/api/v1/history`      | bearer | Record a search (prompt, video, clips snapshot)| 
| DELETE | `/api/v1/history/{id}` | bearer | Delete one search                              |
| DELETE | `/api/v1/history`      | bearer | Clear all my search history                    |

`POST /api/v1/history` with `{"video_id": "…", "prompt": "…", "clips": [{"start": 0, "end": 6, "frame": 3, "score": 0.81}], "expanded": true}`:

1. The video must exist and belong to the user (404 otherwise).
2. The clips are stored as an immutable **JSONB snapshot** of what the search
   returned — history replays the exact result, not a re-rank against today's
   index.
3. Deleting a video cascades to its history rows (a record with no video left
   is unplayable).

## Authentication

Signup, login and session refresh live in `app/auth/`.

| Method | Route                  | Auth            | Purpose                                        |
| ------ | ---------------------- | --------------- | ---------------------------------------------- |
| POST   | `/api/v1/auth/signup`  | —               | Create an account, sign in immediately (201)   |
| POST   | `/api/v1/auth/login`   | —               | Exchange credentials for tokens                |
| POST   | `/api/v1/auth/refresh` | refresh cookie  | Rotate the refresh token, mint a new access token |
| POST   | `/api/v1/auth/logout`  | refresh cookie  | Revoke the current session                     |
| POST   | `/api/v1/auth/logout-all` | bearer       | Revoke every session for the account           |
| GET    | `/api/v1/auth/me`      | bearer          | The signed-in account                          |

**Token model**

- **Access token** — a 15-minute JWT (`ACCESS_TOKEN_TTL_MINUTES`) returned in
  the response body. The client keeps it in memory and sends it as
  `Authorization: Bearer …`. It is never written to `localStorage`.
- **Refresh token** — an opaque 64-byte random string in an httpOnly cookie
  scoped to `/api/v1/auth`, valid 30 days. Only its SHA-256 digest is stored,
  so a database leak yields no usable sessions.

**Expiry handling.** When the access token expires the API answers `401`. The
frontend interceptor (`src/lib/http.ts`) catches that, calls `/auth/refresh`
once — concurrent 401s share one refresh — and replays the original request
with the new token. It also refreshes pre-emptively 60s before expiry.

**Rotation and reuse detection.** Every refresh revokes the presented token and
issues a new one. Presenting an already-revoked token means it leaked, so every
session for that user is revoked.

Passwords are hashed with **Argon2id**. Login answers with an identical message
and comparable timing whether or not the email exists, so it cannot be used to
enumerate accounts.

## Database and migrations

SQLAlchemy 2.0 (async, asyncpg) with Alembic.

```bash
uv run alembic upgrade head                      # apply migrations
uv run alembic revision --autogenerate -m "..."  # after changing models
uv run alembic check                             # fail if models drifted from the schema
uv run alembic downgrade -1                      # roll back one revision
```

`migrations/env.py` reads `DATABASE_URL` from settings, so credentials live in
`.env` only. New model modules must be imported in `app/db/metadata.py`, or
autogenerate will not see them.

Inside Docker:

```bash
docker compose run --rm backend alembic upgrade head
```

## Project structure

```
app/
├── main.py              # FastAPI app: lifespan, CORS, routers
├── core/
│   ├── config.py        # pydantic-settings Settings
│   └── logging.py       # structured logging setup
├── db/
│   ├── base.py          # DeclarativeBase + timestamp mixin
│   ├── session.py       # async engine, session factory, get_db
│   └── metadata.py      # single import point for Alembic
├── auth/                # the whole auth feature
│   ├── models.py        # users, refresh_tokens
│   ├── schemas.py       # request/response contracts
│   ├── security.py      # Argon2 hashing, JWT, token generation
│   ├── service.py       # signup / login / refresh / logout logic
│   ├── deps.py          # DbSession, CurrentUser
│   └── routes.py        # /api/v1/auth/*
├── api/
│   └── routes/
│       ├── health.py    # GET /api/v1/health
│       └── search.py    # GET /api/v1/search (demo catalog)
└── schemas/
    └── video.py         # VideoItem / SearchResponse models
migrations/              # Alembic environment + versions
tests/
├── test_api.py          # health + search
├── test_security.py     # hashing and JWT units (no database)
└── test_auth_api.py     # full auth flow (needs TEST_DATABASE_URL)
```

### Running the database tests

Auth route tests need a real Postgres and are skipped without one. Point them at
a **dedicated throwaway database** — they `TRUNCATE` between cases:

```bash
TEST_DATABASE_URL=postgresql://videosearch:pass@localhost:5434/videosearch_test uv run pytest
```

Two guards make that safe: the suite refuses to run if the target database
already contains user rows, and it only drops the schema if it created it.

### Migration style

Migrations are written as literal SQL inside `op.execute(...)` rather than
`op.create_table()` builder calls, so a review shows exactly what Postgres will
run. One statement per `op.execute` — asyncpg prepares each statement and
rejects multiple commands in a single string.

After editing models, autogenerate a draft and then rewrite the body as SQL:

```bash
uv run alembic revision --autogenerate -m "add something"
uv run alembic check   # must report "No new upgrade operations detected"
```

## Docker

### Full stack (API + Postgres with pgvector) via docker compose

```bash
docker compose up --build    # starts Postgres + the API on :3006
```

The DB uses the official **pgvector** image (`pgvector/pgvector:pg16`) — plain
Postgres 16 plus the `vector` extension for semantic search. The extension is
enabled automatically on first boot by `db/init/01-vector.sql`
(`CREATE EXTENSION IF NOT EXISTS vector;`).

Credentials come from `.env` (`POSTGRES_*` vars); the DB data is persisted in
the `postgres_data` volume. Stop with `docker compose down` (add `-v` to also
wipe the database).

> ℹ️ This project maps the DB to host port **5433** (`POSTGRES_PORT` in `.env`)
> to avoid clashing with another Postgres already running on 5432.

> ⚠️ Init scripts only run when the data volume is empty. If you previously
> started the old plain-Postgres image, run `docker compose down -v` once so the
> pgvector image can initialize a fresh volume with the extension enabled.

> ⚠️ Init scripts only run when the data volume is empty. If you previously
> started the old plain-Postgres image, run `docker compose down -v` once so the
> pgvector image can initialize a fresh volume with the extension enabled.

### API image only

```bash
docker build -t videosearchbackend .
docker run -p 3006:3006 videosearchbackend
```

The image installs with `uv sync --frozen --no-dev` and runs uvicorn on port
3006 with a container health check.

## Next steps to production

- Replace the demo catalog in `app/api/routes/search.py` with a real video
  search integration (e.g. YouTube Data API) using `VITE_YOUTUBE_API_KEY`-style
  secrets via env vars.
- Add a database (e.g. SQLModel/SQLAlchemy + Postgres) for persisted data.
- Add auth (e.g. JWT) if the API needs protected endpoints.
