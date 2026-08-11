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
 * Byte-range passthrough: the browser's `Range` header is forwarded to R2 and
 * the `206 Partial Content` / `Content-Range` headers are returned so `<video>`
 * seeking works. CORS is limited to the configured frontend origins.
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
  return new Set(['http://localhost:5174', 'http://127.0.0.1:5174'])
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

    // Byte-range passthrough: pass the browser's Range straight to R2.
    const range = request.headers.get('Range')
    const object = await env.VIDEO_BUCKET.get(key, range ? { range } : undefined)
    if (object === null) {
      return new Response('Not found', { status: 404, headers: cors })
    }

    const headers = new Headers(cors)
    object.writeHttpMetadata(headers)
    headers.set('Content-Disposition', 'inline')
    headers.set('Accept-Ranges', 'bytes')

    // `object.range` is a `bytes a-b/total` string at runtime (the types
    // declare a wider union, hence the String() coercion for the header).
    const servedRange = object.range ? String(object.range) : null
    if (servedRange) {
      headers.set('Content-Range', servedRange)
      const match = /bytes (\d+)-(\d+)\/(\d+)/.exec(servedRange)
      if (match) {
        headers.set(
          'Content-Length',
          String(Number(match[2]) - Number(match[1]) + 1),
        )
      }
    } else {
      headers.set('Content-Length', String(object.size))
    }

    const status = range && servedRange ? 206 : 200
    return new Response(request.method === 'HEAD' ? null : object.body, {
      status,
      headers,
    })
  },
}
