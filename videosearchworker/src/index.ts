/**
 * videosearch-stream — edge playback proxy.
 *
 * Serves video bytes directly from R2 on Cloudflare's network so the FastAPI
 * backend never proxies media. Requests must carry a short-lived HMAC
 * signature minted by the backend (`GET /api/v1/videos/{id}/stream-url`).
 *
 * URL shape handled by this Worker:
 *
 *   /stream/<owner>/<video-id>.<ext>?expires=<unix>&sig=<hex hmac-sha256>
 *
 * The signature covers `"<key>:<expires>"` using the shared secret
 * `STREAM_SIGN_SECRET` (set with `wrangler secret put`).
 *
 * Byte-range passthrough: the browser's `Range` header is parsed into the R2
 * range object form and forwarded to R2; the `206 Partial Content` /
 * `Content-Range` headers are built from the response so `<video>` seeking
 * works. CORS is limited to the configured frontend origins.
 */

export interface Env {
  /** R2 bucket binding — matches `[[r2_buckets]]` in wrangler.toml. */
  VIDEO_BUCKET: R2Bucket
  /** Shared HMAC secret — must equal the backend's STREAM_SIGNING_SECRET. */
  STREAM_SIGN_SECRET: string
  /**
   * Comma-separated frontend origins allowed to play videos back (canvas
   * thumbnail capture needs CORS). Falls back to localhost dev origins.
   */
  ALLOWED_ORIGINS?: string
}

function allowedOrigins(env: Env): Set<string> {
  if (env.ALLOWED_ORIGINS) {
    return new Set(env.ALLOWED_ORIGINS.split(',').map((o) => o.trim()).filter(Boolean))
  }
  return new Set(['http://localhost:5180', 'http://127.0.0.1:5180'])
}

const ROUTE_PREFIX = '/stream/'

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

async function hmacHex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  )
  const signature = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message))
  return hex(signature)
}

/** Constant-time hex comparison so timing leaks nothing about the secret. */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i)
  return diff === 0
}

async function verifySignature(
  request: Request,
  key: string,
  env: Env,
): Promise<boolean> {
  const url = new URL(request.url)
  const expires = url.searchParams.get('expires') ?? ''
  const provided = url.searchParams.get('sig') ?? ''
  if (!expires || !provided) return false

  const expected = await hmacHex(env.STREAM_SIGN_SECRET, `${key}:${expires}`)
  if (!timingSafeEqual(expected, provided)) return false
  return Number(expires) > Date.now() / 1000
}

function corsHeaders(origin: string | null, env: Env): Record<string, string> {
  if (!origin || !allowedOrigins(env).has(origin)) return {}
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
    'Access-Control-Allow-Headers': 'Range',
    'Access-Control-Expose-Headers': 'Content-Range, Content-Length, Accept-Ranges',
    'Vary': 'Origin',
  }
}

/**
 * Parse an HTTP Range header ("bytes=0-1023", "bytes=1024-", "bytes=-512")
 * into the object form R2's get() accepts. Returns null for malformed or
 * multi-range requests (we answer those with a full 200, which is safe).
 */
function parseRange(header: string): R2Range | null {
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim())
  if (!match) return null
  const startRaw = match[1]
  const endRaw = match[2]
  if (startRaw === '' && endRaw === '') return null
  if (startRaw === '') {
    // Suffix form: last N bytes.
    const suffix = Number(endRaw)
    return suffix > 0 ? { suffix } : null
  }
  const offset = Number(startRaw)
  if (endRaw === '') {
    // Open-ended: from offset to end of file.
    return { offset }
  }
  const end = Number(endRaw)
  if (end < offset) return null
  return { offset, length: end - offset + 1 }
}

/** "Content-Range" header value for a satisfied range, or null if unsatisfiable. */
function contentRange(range: R2Range, size: number): string | null {
  if ('suffix' in range) {
    if (range.suffix <= 0 || size <= 0) return null
    const start = Math.max(0, size - range.suffix)
    return `bytes ${start}-${size - 1}/${size}`
  }
  const offset = range.offset ?? 0
  if (offset >= size) return null
  const end = offset + (range.length ?? size - offset) - 1
  return `bytes ${offset}-${Math.min(end, size - 1)}/${size}`
}

/** Number of bytes the partial response carries, or null if unsatisfiable. */
function partialLength(range: R2Range, size: number): number | null {
  if ('suffix' in range) return Math.min(range.suffix, size)
  const offset = range.offset ?? 0
  if (offset >= size) return null
  return Math.min(range.length ?? size - offset, size - offset)
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url)
    const cors = corsHeaders(request.headers.get('Origin'), env)

    // CORS preflight from the frontend.
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors })
    }

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method not allowed', { status: 405, headers: cors })
    }

    // `/stream/<owner>/<video-id>.<ext>` → the object key in the bucket.
    if (!url.pathname.startsWith(ROUTE_PREFIX)) {
      return new Response('Not found', { status: 404, headers: cors })
    }
    const key = url.pathname.slice(ROUTE_PREFIX.length)
    if (!key) return new Response('Not found', { status: 404, headers: cors })

    if (!(await verifySignature(request, key, env))) {
      return new Response('Forbidden', { status: 403, headers: cors })
    }

    const rangeHeader = request.headers.get('Range')
    const range = rangeHeader ? parseRange(rangeHeader) : null

    let object: R2ObjectBody | R2Object | null
    try {
      object = await env.VIDEO_BUCKET.get(key, range ? { range } : undefined)
    } catch {
      // R2 throws for an unsatisfiable range (e.g. start beyond EOF).
      return new Response('Requested range not satisfiable', { status: 416, headers: cors })
    }
    if (object === null) {
      return new Response('Not found', { status: 404, headers: cors })
    }

    const headers = new Headers(cors)
    object.writeHttpMetadata(headers)
    headers.set('Content-Disposition', 'inline')
    headers.set('Accept-Ranges', 'bytes')

    let status = 200
    if (range) {
      const served = contentRange(range, object.size)
      const length = partialLength(range, object.size)
      if (served === null || length === null) {
        return new Response('Requested range not satisfiable', { status: 416, headers: cors })
      }
      headers.set('Content-Range', served)
      headers.set('Content-Length', String(length))
      status = 206
    } else {
      headers.set('Content-Length', String(object.size))
    }

    // No conditional reads are used, so get() always yields an R2ObjectBody
    // (the R2Object variant only appears when a precondition fails).
    return new Response(request.method === 'HEAD' ? null : (object as R2ObjectBody).body, {
      status,
      headers,
    })
  },
}
