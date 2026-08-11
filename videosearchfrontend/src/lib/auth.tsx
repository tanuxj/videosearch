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
    const onExpired = () => setUser(null)
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired)
  }, [])

  const signUp = useCallback(
    async (name: string, email: string, password: string) => {
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

  const value = useMemo<AuthValue>(
    () => ({ user, ready, signUp, signIn, signOut }),
    [user, ready, signUp, signIn, signOut],
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
