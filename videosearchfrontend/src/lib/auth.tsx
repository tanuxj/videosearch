import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import {
  API_ENABLED,
  AUTH_ENABLED,
  AUTH_EXPIRED_EVENT,
  ApiError,
  apiFetch,
  refreshSession,
  setSession,
} from './http'
import type { ApiUser, TokenPayload } from './http'

/**
 * Auth state.
 *
 * With `VITE_API_URL` set, this talks to the FastAPI backend: signup/login
 * return a 15-minute access token (held in memory by `lib/http`) plus an
 * httpOnly refresh cookie, and the session is restored on page load by
 * calling `/auth/refresh`.
 *
 * With no API URL configured it falls back to a browser-local demo store so
 * the UI stays walkable without a server. The fallback is opt-out only —
 * if an API is configured and unreachable, sign-in fails loudly rather than
 * silently pretending to succeed.
 *
 * With `VITE_AUTH_ENABLED=false` none of that happens: there is no account
 * system. Each browser instead gets a throwaway session, the way a disposable
 * inbox does — the backend issues an httpOnly `vs_guest` cookie on the first
 * request and derives an account from it, so a visitor sees only the videos
 * they added and a new browser starts empty. `GET /auth/me` is what tells the
 * client which session it is in; the rest of the app reads `user` exactly as
 * before, so upload, indexing, search and clips need no changes.
 */

export type User = {
  id: string
  name: string
  email: string
}

function toUser(user: ApiUser): User {
  return { id: user.id, name: user.name, email: user.email }
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join('')
}

/* ── Open access (accounts disabled) ─────────────────────── */

/**
 * Stand-in identity for open access when the server cannot be asked who we
 * are — no API configured (demo mode), or the API is unreachable.
 *
 * The id matches `GUEST_USER_ID` in the backend's `app/auth/guest.py`, which
 * is the account its "shared" mode uses. Local storage keys are scoped by
 * user id (`vs.videos.<id>`), so a real session's videos never mix with this
 * fallback's.
 */
export const GUEST_USER: User = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'Guest',
  email: 'guest@videosearch.internal',
}

/** Thrown if a sign-in form is somehow still reachable with accounts off. */
function accountsDisabled(): Error {
  return new Error(
    'Accounts are disabled — no sign-in is needed. Upload a video and search it.',
  )
}

/* ── Local demo fallback (no backend configured) ─────────── */

type StoredUser = User & { passwordHash: string }

const USERS_KEY = 'vs.users'
const SESSION_KEY = 'vs.session'

function readLocalUsers(): StoredUser[] {
  try {
    const raw = localStorage.getItem(USERS_KEY)
    return raw ? (JSON.parse(raw) as StoredUser[]) : []
  } catch {
    return []
  }
}

async function weakHash(password: string): Promise<string> {
  const bytes = new TextEncoder().encode(`vs:${password}`)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

/* ── Provider ───────────────────────────────────────────── */

type AuthValue = {
  user: User | null
  /** False until the stored session has been checked. */
  ready: boolean
  signUp: (name: string, email: string, password: string) => Promise<void>
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
  /**
   * Open access only: abandon this browser's session and start an empty one.
   * The previous session's videos are left on the server but become
   * unreachable — the cookie was the only way back to them. Reloads the page.
   */
  resetSession: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  // Restore the session on load: the refresh cookie survives a reload even
  // though the access token (memory only) does not.
  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      // Open access: the session cookie is httpOnly, so the only way to learn
      // which session this browser is in is to ask. The request also *starts*
      // the session when there is no cookie yet — the response sets one.
      if (!AUTH_ENABLED) {
        let identity = GUEST_USER
        if (API_ENABLED) {
          try {
            identity = toUser(
              await apiFetch<ApiUser>('/api/v1/auth/me', { auth: false }),
            )
          } catch {
            // Unreachable API: fall back so the UI still renders rather than
            // hanging on a blank screen. Storage keys stay separate.
          }
        }
        if (!cancelled) {
          setUser(identity)
          setReady(true)
        }
        return
      }

      if (API_ENABLED) {
        const payload = await refreshSession()
        if (!cancelled) setUser(payload ? toUser(payload.user) : null)
      } else {
        try {
          const raw = localStorage.getItem(SESSION_KEY)
          if (raw && !cancelled) setUser(JSON.parse(raw) as User)
        } catch {
          localStorage.removeItem(SESSION_KEY)
        }
      }
      if (!cancelled) setReady(true)
    }

    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [])

  // A failed refresh means the refresh token is gone, expired or was
  // replayed — drop the user straight back to signed-out.
  useEffect(() => {
    if (!AUTH_ENABLED) return
    const onExpired = () => setUser(null)
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired)
  }, [])

  const signUp = useCallback(
    async (name: string, email: string, password: string) => {
      if (!AUTH_ENABLED) throw accountsDisabled()

      if (API_ENABLED) {
        const payload = await apiFetch<TokenPayload>('/api/v1/auth/signup', {
          method: 'POST',
          auth: false,
          body: JSON.stringify({ name: name.trim(), email: email.trim(), password }),
        })
        setSession(payload)
        setUser(toUser(payload.user))
        return
      }

      const normalized = email.trim().toLowerCase()
      const users = readLocalUsers()
      if (users.some((u) => u.email === normalized)) {
        throw new Error('An account with that email already exists.')
      }
      const created: StoredUser = {
        id: crypto.randomUUID(),
        name: name.trim(),
        email: normalized,
        passwordHash: await weakHash(password),
      }
      localStorage.setItem(USERS_KEY, JSON.stringify([...users, created]))
      const next = { id: created.id, name: created.name, email: created.email }
      localStorage.setItem(SESSION_KEY, JSON.stringify(next))
      setUser(next)
    },
    [],
  )

  const signIn = useCallback(async (email: string, password: string) => {
    if (!AUTH_ENABLED) throw accountsDisabled()

    if (API_ENABLED) {
      const payload = await apiFetch<TokenPayload>('/api/v1/auth/login', {
        method: 'POST',
        auth: false,
        body: JSON.stringify({ email: email.trim(), password }),
      })
      setSession(payload)
      setUser(toUser(payload.user))
      return
    }

    const normalized = email.trim().toLowerCase()
    const found = readLocalUsers().find((u) => u.email === normalized)
    if (!found || found.passwordHash !== (await weakHash(password))) {
      throw new Error('Email or password is incorrect.')
    }
    const next = { id: found.id, name: found.name, email: found.email }
    localStorage.setItem(SESSION_KEY, JSON.stringify(next))
    setUser(next)
  }, [])

  const signOut = useCallback(() => {
    // Nothing to sign out of with accounts off, and clearing `user` would
    // strand the app on a login page that no longer exists.
    if (!AUTH_ENABLED) return

    // Clear locally first so the UI never looks signed in while the
    // revocation request is still in flight.
    setUser(null)
    setSession(null)

    if (API_ENABLED) {
      void apiFetch('/api/v1/auth/logout', { method: 'POST', auth: false }).catch(
        () => {
          /* already signed out locally; nothing useful to show */
        },
      )
    } else {
      localStorage.removeItem(SESSION_KEY)
    }
  }, [])

  const resetSession = useCallback(async () => {
    if (AUTH_ENABLED) return

    if (API_ENABLED) {
      await apiFetch('/api/v1/auth/session/reset', {
        method: 'POST',
        auth: false,
      })
    } else {
      // Demo mode keeps its library in localStorage under the fallback id.
      localStorage.removeItem(`vs.videos.${GUEST_USER.id}`)
      localStorage.removeItem(`vs.history.${GUEST_USER.id}`)
    }

    // Reload rather than re-fetching in place: the old session's video list,
    // blob URLs, thumbnails and in-flight requests are all invalid now, and a
    // reload is the one way to be sure none of them survive.
    window.location.reload()
  }, [])

  const value = useMemo<AuthValue>(
    () => ({ user, ready, signUp, signIn, signOut, resetSession }),
    [user, ready, signUp, signIn, signOut, resetSession],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** Human-readable message for a caught auth failure. */
export function authErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) {
    // fetch() rejects with a TypeError when the server is unreachable.
    if (error.name === 'TypeError') {
      return 'Cannot reach the server. Is the API running?'
    }
    return error.message
  }
  return fallback
}
