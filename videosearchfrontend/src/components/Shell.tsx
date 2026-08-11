import type { ReactNode } from 'react'
import { Link, useRoute } from '../lib/router'
import { initials, useAuth } from '../lib/auth'
import {
  GridIcon,
  PlayIcon,
  SearchIcon,
  SignOutIcon,
  UploadIcon,
} from './Icons'

export const APP_NAME: string = import.meta.env.VITE_APP_NAME || 'VideoSearch'

export function Brand({ to = '/' }: { to?: string }) {
  return (
    <Link to={to} className="brand" aria-label={`${APP_NAME} home`}>
      <span className="brand-mark">
        <PlayIcon />
      </span>
      <span>{APP_NAME}</span>
    </Link>
  )
}

/* ── Public / marketing pages ───────────────────────────── */

export function MarketingShell({ children }: { children: ReactNode }) {
  const { user } = useAuth()

  return (
    <div className="marketing">
      <header className="top-nav">
        <div className="top-nav-inner">
          <Brand />
          <nav className="top-nav-links">
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <a href="#pricing">Pricing</a>
          </nav>
          <div className="top-nav-actions">
            {user ? (
              <Link to="/dashboard" className="btn btn-primary btn-sm">
                Open dashboard
              </Link>
            ) : (
              <>
                <Link to="/login" className="btn btn-quiet btn-sm">
                  Sign in
                </Link>
                <Link to="/signup" className="btn btn-primary btn-sm">
                  Get started
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="shell-main">{children}</main>

      <footer className="site-footer">
        <div className="site-footer-inner">
          <span>
            © {new Date().getFullYear()} {APP_NAME}
          </span>
          <nav>
            <a href="#privacy">Privacy</a>
            <a href="#terms">Terms</a>
            <a href="#docs">Docs</a>
          </nav>
        </div>
      </footer>
    </div>
  )
}

/* ── Authenticated app ──────────────────────────────────── */

const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: GridIcon },
  { to: '/upload', label: 'Upload', icon: UploadIcon },
  { to: '/search', label: 'Search clips', icon: SearchIcon },
]

type AppShellProps = {
  title: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
}

export function AppShell({ title, subtitle, actions, children }: AppShellProps) {
  const route = useRoute()
  const { user, signOut } = useAuth()

  return (
    <div className="app-shell">
      <aside className="side">
        <div className="side-brand">
          <Brand to="/dashboard" />
        </div>

        <p className="side-label">Workspace</p>
        <nav className="side-nav">
          {NAV.map((item) => {
            const Icon = item.icon
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`side-link${route === item.to ? ' is-active' : ''}`}
                aria-current={route === item.to ? 'page' : undefined}
              >
                <Icon />
                <span>{item.label}</span>
              </Link>
            )
          })}
        </nav>

        <div className="side-foot">
          {user && (
            <div className="side-user">
              <span className="avatar">{initials(user.name)}</span>
              <div>
                <b>{user.name}</b>
                <span>{user.email}</span>
              </div>
            </div>
          )}
          <button
            type="button"
            className="btn btn-quiet btn-sm side-signout"
            onClick={signOut}
          >
            <SignOutIcon />
            Sign out
          </button>
        </div>
      </aside>

      <div className="app-body">
        <header className="app-topbar">
          <div>
            <h1>{title}</h1>
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions && <div className="app-topbar-actions">{actions}</div>}
        </header>
        <div className="page">{children}</div>
      </div>
    </div>
  )
}
