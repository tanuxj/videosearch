import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'

/**
 * Demo authentication — accounts live in this browser's localStorage only.
 * There is no server, no session token and no real security here; it exists
 * so the UI flow (sign up → sign in → dashboard) is walkable end to end.
 * Swap `signUp`/`signIn` for real backend calls when auth lands.
 */

export type User = {
  id: string
  name: string
  email: string
}

type StoredUser = User & { passwordHash: string }

const USERS_KEY = 'vs.users'
const SESSION_KEY = 'vs.session'

function readUsers(): StoredUser[] {
  try {
    const raw = localStorage.getItem(USERS_KEY)
    return raw ? (JSON.parse(raw) as StoredUser[]) : []
  } catch {
    return []
  }
}

function writeUsers(users: StoredUser[]): void {
  localStorage.setItem(USERS_KEY, JSON.stringify(users))
}

async function hash(password: string): Promise<string> {
  const bytes = new TextEncoder().encode(`vs:${password}`)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join('')
}

type AuthValue = {
  user: User | null
  ready: boolean
  signUp: (name: string, email: string, password: string) => Promise<void>
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SESSION_KEY)
      if (raw) setUser(JSON.parse(raw) as User)
    } catch {
      localStorage.removeItem(SESSION_KEY)
    }
    setReady(true)
  }, [])

  const persist = useCallback((next: User) => {
    localStorage.setItem(SESSION_KEY, JSON.stringify(next))
    setUser(next)
  }, [])

  const signUp = useCallback(
    async (name: string, email: string, password: string) => {
      const normalized = email.trim().toLowerCase()
      const users = readUsers()
      if (users.some((u) => u.email === normalized)) {
        throw new Error('An account with that email already exists.')
      }
      const created: StoredUser = {
        id: crypto.randomUUID(),
        name: name.trim(),
        email: normalized,
        passwordHash: await hash(password),
      }
      writeUsers([...users, created])
      persist({ id: created.id, name: created.name, email: created.email })
    },
    [persist],
  )

  const signIn = useCallback(
    async (email: string, password: string) => {
      const normalized = email.trim().toLowerCase()
      const found = readUsers().find((u) => u.email === normalized)
      const passwordHash = await hash(password)
      if (!found || found.passwordHash !== passwordHash) {
        throw new Error('Email or password is incorrect.')
      }
      persist({ id: found.id, name: found.name, email: found.email })
    },
    [persist],
  )

  const signOut = useCallback(() => {
    localStorage.removeItem(SESSION_KEY)
    setUser(null)
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
