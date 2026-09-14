/**
 * API client with transparent access-token refresh.
 *
 * The access token lives in memory only (never localStorage — anything
 * readable by JavaScript is readable by an XSS payload). The refresh token
 * is an httpOnly cookie the browser attaches to `/api/v1/auth` calls, which
 * is why every request here sets `credentials: 'include'`.
 *
 * Flow when the 15-minute access token expires:
 *   request → 401 → POST /auth/refresh → retry original request once
 * Concurrent 401s share a single refresh call rather than stampeding it.
 */

const RAW_API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

/**
 * Same-origin mode: call the API through the page's own origin.
 *
 * This exists because the refresh cookie is host-only with `SameSite=Lax`. Point
 * the browser at `localhost:5180` while the API is addressed as
 * `127.0.0.1:3006` and those are *different sites*, so the browser refuses to
 * attach the cookie to the `POST /auth/refresh` — Lax allows top-level
 * navigations only. Refresh then 401s and the session dies the moment the
 * 15-minute access token expires, which looks exactly like "refresh is broken".
 *
 * With this on, `vite.config.ts` proxies `/api` to the backend, so the request
 * never leaves the page's origin: the cookie is first-party, SameSite stops
 * mattering, and it works whichever hostname you happen to type.
 */
const SAME_ORIGIN = import.meta.env.VITE_API_SAME_ORIGIN === 'true'

/** '' means "relative to this origin", which is what the dev proxy wants. */
const API_URL = SAME_ORIGIN ? '' : RAW_API_URL

/** False when no backend is configured — the app then runs on local demo auth. */
export const API_ENABLED = SAME_ORIGIN || Boolean(RAW_API_URL)

/**
 * Open-access mode: `VITE_AUTH_ENABLED=false` turns the account system off.
 *
 * There is then no sign-up, no sign-in and no token to carry — the backend
 * (which must have `AUTH_ENABLED=false` to match) serves every request as one
 * shared guest account. Everything below that deals with access tokens,
 * refreshing and expiry simply never runs, so a request is a plain `fetch`.
 *
 * Nothing here is deleted: flip this back to true, restart the dev server,
 * and the full token flow is live again.
 */
export const AUTH_ENABLED = import.meta.env.VITE_AUTH_ENABLED !== 'false'

export type ApiUser = {
  id: string
  name: string
  email: string
  created_at: string
}

export type TokenPayload = {
  access_token: string
  token_type: string
  expires_in: number
  user: ApiUser
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let accessToken: string | null = null
let refreshInFlight: Promise<TokenPayload | null> | null = null
let expiryTimer: ReturnType<typeof setTimeout> | undefined

/** Fired when refresh fails — the session is over and the UI must sign out. */
export const AUTH_EXPIRED_EVENT = 'auth:expired'

export function getAccessToken(): string | null {
  return accessToken
}

export function url(path: string): string {
  return `${API_URL}${path}`
}

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    // FastAPI validation errors arrive as a list of {loc, msg}.
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  } catch {
    /* not JSON */
  }
  return fallback
}

/** Schedule a refresh shortly before the current token expires. */
function scheduleRefresh(expiresIn: number): void {
  clearTimeout(expiryTimer)
  // 60s of head-room, and never less than 10s to avoid a tight loop.
  const delay = Math.max(10, expiresIn - 60) * 1000
  expiryTimer = setTimeout(() => {
    void refreshSession()
  }, delay)
}

export function setSession(payload: TokenPayload | null): void {
  accessToken = payload?.access_token ?? null
  if (payload) scheduleRefresh(payload.expires_in)
  else clearTimeout(expiryTimer)
}

/**
 * Exchange the refresh cookie for a new access token. Concurrent callers
 * await the same request; a failure clears the session and notifies the app.
 */
export function refreshSession(): Promise<TokenPayload | null> {
  // No cookie to exchange in open-access mode, and `/auth/refresh` answers
  // 404 there — so never ask.
  if (!API_ENABLED || !AUTH_ENABLED) return Promise.resolve(null)

  refreshInFlight ??= fetch(url('/api/v1/auth/refresh'), {
    method: 'POST',
    credentials: 'include',
  })
    .then(async (response) => {
      if (!response.ok) return null
      const payload = (await response.json()) as TokenPayload
      setSession(payload)
      return payload
    })
    .catch(() => null)
    .finally(() => {
      refreshInFlight = null
    })

  return refreshInFlight
}

type FetchOptions = RequestInit & { auth?: boolean; parseBlob?: boolean }

/**
 * `fetch` for this API: JSON in, JSON out, bearer token attached, and one
 * automatic retry after a refresh when the token has expired.
 */
export async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { auth = true, headers, ...rest } = options

  const send = (token: string | null): Promise<Response> =>
    fetch(url(path), {
      ...rest,
      credentials: 'include',
      headers: {
        ...(rest.body ? { 'Content-Type': 'application/json' } : {}),
        ...(auth && token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
    })

  let response = await send(accessToken)

  // Expired access token: refresh once, then replay the original request.
  // With accounts off a 401 cannot be an expiry, so it falls through to the
  // error below rather than tearing down a session that does not exist.
  if (response.status === 401 && auth && AUTH_ENABLED) {
    const refreshed = await refreshSession()
    if (refreshed) {
      response = await send(refreshed.access_token)
    } else {
      setSession(null)
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response, response.statusText))
  }

  if (response.status === 204) return undefined as T
  if (options.parseBlob) return (await response.blob()) as T
  return (await response.json()) as T
}
