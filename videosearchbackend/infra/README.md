# Infrastructure config

## `r2-cors.json` — bucket CORS for direct uploads

The browser PUTs video bytes straight to R2, so the **bucket** (not just the
API) must allow the frontend origin. Without this the browser blocks the
request before it is sent, and the upload fails with a bare network error.

Use the npm scripts — they run the pinned wrangler and resolve the file path
correctly **from any directory**:

```bash
npm run cors:list --prefix videosearchworker   # what is live now
npm run cors:set  --prefix videosearchworker   # apply r2-cors.json
```

### If you get `Unknown arguments: cors`

You invoked `npx wrangler` directly from a directory without a local install,
so it fell back to a global **3.x** — and `r2 bucket cors` only exists in
**wrangler 4**:

```bash
cd videosearchbackend  && npx wrangler --version   # 3.68.0 — no cors command
cd videosearchworker   && npx wrangler --version   # 4.120.0 — has it
```

The npm scripts above avoid this entirely. To call wrangler by hand, either
`cd videosearchworker` first or force a modern one: `npx wrangler@4 …`.

Add production frontend origins to the file as they come along — `set`
replaces the whole policy, so every origin must be listed each time.

### Why this project has its own bucket

VideoSearch used to share `safeguard` with another project. R2 CORS, lifecycle
rules and event notifications are all **bucket-wide and replaced wholesale**,
and an API token reaches every object in the bucket — so one project's change
could break, or delete, another's data.

`searchinvideo` is VideoSearch's own bucket. Keep it that way: a second tenant
brings all of that back.

### Two formats — mind which one you are pasting into

The same policy is expressed two different ways depending on where you set it.
Both files here say exactly the same thing.

| Where | File | Shape |
| ----- | ---- | ----- |
| `wrangler r2 bucket cors set` | `r2-cors.json` | `{ "rules": [ { "allowed": { "origins", "methods", "headers" }, "exposeHeaders", "maxAgeSeconds" } ] }` |
| Cloudflare dashboard → bucket → Settings → CORS Policy | `r2-cors-dashboard.json` | S3 style: top-level array of `{ "AllowedOrigins", "AllowedMethods", "AllowedHeaders", "ExposeHeaders", "MaxAgeSeconds" }` |

Feeding the S3-style file to wrangler fails with `The CORS configuration file
must contain a 'rules' array`. **Keep the two files in sync** — editing one and
forgetting the other is how origins go missing.

### Why `headers: ["*"]`

The presigned PUT is signed with a `Content-Type`, so the browser must send
that header. `*` was already the bucket's setting; narrowing it to
`content-type` would risk breaking the other project's uploads if they send
anything else.
