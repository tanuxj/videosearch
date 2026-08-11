# videosearch-stream — edge playback Worker

A Cloudflare Worker that serves your R2 videos directly from Cloudflare's
edge network, so the FastAPI backend never proxies media bytes.

## Why

Today the browser streams through the API: `R2 → FastAPI → browser`. Every
byte of every video passes through your tiny server (bandwidth + CPU). This
Worker replaces that with `R2 → browser`, cutting API load to ~zero for
playback.

## How it works

1. **Backend mints a signed URL** — `GET /api/v1/videos/{id}/stream-url`
   returns `https://<worker>/stream/<owner>/<video>.mp4?expires=...&sig=...`
   (HMAC-SHA256 over `"<key>:<expires>"` with `STREAM_SIGNING_SECRET`).
2. **Browser plays that URL** — a `<video>` element streams it directly;
   the Worker verifies the signature + expiry, then reads the object from R2
   with **byte-range passthrough** (so seeking works, `206 Partial Content`).
3. **CORS** is limited to the frontend origins so the app can also grab
   frame thumbnails from the stream (canvas capture).

## Deploy

```bash
cd videosearchworker
npm install

# 1. Share the signing secret with the backend
npx wrangler secret put STREAM_SIGN_SECRET
#    paste the SAME value as STREAM_SIGNING_SECRET in the backend's .env

# 2. (Production) allow your real frontend origin to stream via CORS
npx wrangler secret put ALLOWED_ORIGINS -- "https://app.example.com"

# 3. Deploy
npx wrangler deploy
```

Set in the **backend** `.env` **only after `wrangler deploy` succeeds** — the
frontend falls back to the API-proxied stream while `STREAM_WORKER_BASE_URL`
is empty, so if you flip the env before the Worker is live, playback breaks:

```
STREAM_WORKER_BASE_URL=https://videosearch-stream.<your-account>.workers.dev
STREAM_SIGNING_SECRET=<the same value you put in wrangler>
```

> **Note on signed-URL expiry:** signed URLs are valid for
> `STREAM_URL_TTL_SECONDS` (default 1h). The frontend mints a fresh URL each
> time you pick a video, but a tab left open past the TTL will get a 403 on
> the next seek — just reload the page to re-mint.

Local dev:

```bash
npx wrangler dev          # serves http://localhost:8787
```

## Test locally

With the secret `dev-secret`, mint a URL the same way the backend does:

```bash
python - <<'PY'
import hmac, hashlib, time
key = "owner-id/video-id.mp4"
exp = int(time.time()) + 3600
sig = hmac.new(b"dev-secret", f"{key}:{exp}".encode(), hashlib.sha256).hexdigest()
print(f"http://localhost:8787/stream/{key}?expires={exp}&sig={sig}")
PY
```

Then curl it with a Range header:

```bash
curl -H "Range: bytes=0-1023" "<url-printed-above>"
# expect 206 + Content-Range + the first 1 KB
```

## Files

```
videosearchworker/
├── src/index.ts      # the Worker
├── wrangler.toml     # R2 binding + deploy config
├── package.json      # wrangler tooling
└── tsconfig.json
```

## Why a Worker instead of an R2 public bucket?

R2 objects are private; the FastAPI backend enforces ownership per video.
The Worker keeps that guarantee at the edge: it only serves objects whose
HMAC signature the backend minted for the owning user, for a limited window.
Serving R2 directly with public-read would expose every user's uploads.
