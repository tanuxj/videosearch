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

const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

/** False when no backend is configured — the app then runs on local demo auth. */
export const API_ENABLED = Boolean(API_URL)

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
  if (!API_ENABLED) return Promise.resolve(null)

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
  if (response.status === 401 && auth) {
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
