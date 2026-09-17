import { useEffect, useState, type ReactNode } from 'react'
import { Link, useRoute } from '../lib/router'
import { initials, useAuth } from '../lib/auth'
import { AUTH_ENABLED } from '../lib/http'
import { SINGLE_PAGE, SINGLE_PAGE_ROUTE } from '../lib/features'
import { cn } from '../lib/cn'
import { ButtonLink } from './ui/Button'
import {
  GridIcon,
  FilmIcon,
  MicIcon,
  RecordIcon,
  SearchIcon,
  SignOutIcon,
  TeamsIcon,
  UploadIcon,
} from './Icons'
import { LogoMark, Wordmark } from './Logo'
import { NotificationBell } from './NotificationBell'

export const APP_NAME: string =
  import.meta.env.VITE_APP_NAME || 'SearchInVideo'

export function Brand({ to = '/' }: { to?: string }) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-2.5"
      aria-label={`${APP_NAME} home`}
    >
      <LogoMark className="size-7" />
      <Wordmark name={APP_NAME} />
    </Link>
  )
}

/* ── Public / marketing pages ───────────────────────────── */

// Router links rather than in-page anchors: the homepage is the demo itself
// now, so the public nav is the two pages that exist — plus the auth pair on
// the right.
const MARKETING_LINKS = [
  { to: '/', label: 'Video Search' },
  { to: '/pricing', label: 'Pricing' },
]

export function MarketingShell({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  // The bar only grows a divider once the page has moved — a line across the
  // top of a white hero is just a seam.
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <header
        className={cn(
          'sticky top-0 z-50 bg-surface transition-colors duration-200',
          scrolled ? 'border-b border-line' : 'border-b border-transparent',
        )}
      >
        <div className="mx-auto flex h-16 w-full max-w-[1080px] items-center gap-6 px-6">
          <Brand />
          <nav className="ml-2 hidden items-center gap-1 md:flex">
            {MARKETING_LINKS.map((link) => (
              <Link
                key={link.to}
                to={link.to}
                className="rounded-full px-3 py-1.5 text-[13.5px] text-ink-mid transition-colors hover:bg-surface-sunk hover:text-ink"
              >
                {link.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {user || !AUTH_ENABLED ? (
              <ButtonLink as={Link} to="/search" size="sm">
                Open workspace
              </ButtonLink>
            ) : (
              <>
                <ButtonLink as={Link} to="/login" variant="ghost" size="sm">
                  Log in
                </ButtonLink>
                <ButtonLink as={Link} to="/signup" size="sm">
                  Sign up
                </ButtonLink>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-line">
        <div className="mx-auto flex w-full max-w-[1080px] flex-col items-center justify-between gap-3 px-6 py-7 sm:flex-row">
          <span className="text-[12.5px] text-ink-faint">
            © {new Date().getFullYear()} {APP_NAME}
          </span>
          <nav className="flex items-center gap-5">
            <Link
              to="/pricing"
              className="text-[12.5px] text-ink-faint transition-colors hover:text-ink"
            >
              Pricing
            </Link>
            <Link
              to="/privacy"
              className="text-[12.5px] text-ink-faint transition-colors hover:text-ink"
            >
              Privacy
            </Link>
            <Link
              to="/terms"
              className="text-[12.5px] text-ink-faint transition-colors hover:text-ink"
            >
              Terms
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  )
}

/* ── Authenticated app ──────────────────────────────────── */

const NAV_MAIN = [
  { to: '/search', label: 'Search', icon: SearchIcon },
  { to: '/clips', label: 'Clips', icon: FilmIcon },
  { to: '/record', label: 'Record', icon: RecordIcon },
  { to: '/recordings', label: 'Recordings', icon: MicIcon },
  { to: '/workspaces', label: 'Teams', icon: TeamsIcon },
  { to: '/dashboard', label: 'Library', icon: GridIcon },
]

type AppShellProps = {
  title: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
}

function NavLink({
  to,
  label,
  icon: Icon,
  active,
}: {
  to: string
  label: string
  icon: (props: { className?: string }) => ReactNode
  active: boolean
}) {
  return (
    <Link
      to={to}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] transition-colors',
        '[&_svg]:size-[17px] [&_svg]:shrink-0',
        active
          ? 'bg-surface-sunk font-medium text-ink'
          : 'text-ink-mid hover:bg-surface-soft hover:text-ink',
      )}
    >
      <Icon />
      <span className="truncate">{label}</span>
    </Link>
  )
}

/**
 * Single-page chrome: one header, no navigation.
 *
 * With `VITE_SINGLE_PAGE=true` there is nowhere else to go, so a sidebar of
 * one item would be furniture. The brand moves into the header beside the
 * page title, and the page's own actions (the search page's "Add video") plus
 * the indexing bell keep their places on the right.
 */
/**
 * "New session": the escape hatch for the throwaway-session model.
 *
 * Without it a browser is stuck with one library forever, since the session
 * cookie is httpOnly and cannot be cleared from the page. Confirmed first —
 * the current session's videos become unreachable, and there is no undo.
 */
function NewSessionButton() {
  const { resetSession } = useAuth()
  const [working, setWorking] = useState(false)

  if (AUTH_ENABLED) return null

  async function start() {
    if (working) return
    if (
      !confirm(
        'Start a new session? This browser gets an empty library, and the ' +
          'videos in the current session will no longer be reachable.',
      )
    ) {
      return
    }
    setWorking(true)
    try {
      await resetSession()
    } catch {
      // resetSession reloads on success, so reaching here means it failed.
      setWorking(false)
    }
  }

  return (
    <button
      type="button"
      onClick={() => void start()}
      disabled={working}
      title="Clear this browser's library and start over"
      className="rounded-lg border border-line px-3 py-2 text-[13px] text-ink-dim transition-colors hover:bg-surface-soft hover:text-ink disabled:opacity-60"
    >
      {working ? 'Starting…' : 'New session'}
    </button>
  )
}

function SinglePageShell({ title, subtitle, actions, children }: AppShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <header className="sticky top-0 z-40 flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-line bg-surface px-6 py-3.5">
        <Brand to={SINGLE_PAGE_ROUTE} />

        <div className="hidden h-7 w-px bg-line sm:block" />

        <div className="min-w-0">
          <h1 className="text-[17px] leading-tight font-semibold tracking-[-0.02em] text-ink">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-0.5 text-[12.5px] text-ink-dim">{subtitle}</p>
          )}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <NewSessionButton />
          <NotificationBell />
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      </header>

      <div className="min-w-0 flex-1 px-6 py-6">{children}</div>
    </div>
  )
}

export function AppShell({ title, subtitle, actions, children }: AppShellProps) {
  const route = useRoute()
  const { user, signOut } = useAuth()

  if (SINGLE_PAGE) {
    return (
      <SinglePageShell title={title} subtitle={subtitle} actions={actions}>
        {children}
      </SinglePageShell>
    )
  }

  return (
    <div className="flex min-h-screen bg-surface">
      <aside className="sticky top-0 hidden h-screen w-[240px] shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="flex h-16 items-center px-4">
          <Brand to={AUTH_ENABLED ? '/dashboard' : '/search'} />
        </div>

        <nav className="flex flex-col gap-0.5 px-2">
          {NAV_MAIN.map((item) => (
            <NavLink
              key={item.to}
              {...item}
              active={route === item.to}
            />
          ))}
        </nav>

        {/* Thin rule between "what you do" and "what you own", matching the
            reference's grouped sidebar. */}
        <div className="mx-4 my-3 border-t border-line" />

        <p className="px-4 pb-1.5 text-[11px] font-medium tracking-[0.06em] text-ink-faint uppercase">
          Library
        </p>
        <nav className="flex flex-col gap-0.5 px-2">
          <Link
            to="/search?upload=1"
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] text-ink-mid transition-colors hover:bg-surface-soft hover:text-ink [&_svg]:size-[17px]"
          >
            <UploadIcon />
            <span>Add a video</span>
          </Link>
        </nav>

        <div className="mt-auto border-t border-line p-2">
          {user && (
            <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-brand text-[12px] font-semibold text-white">
                {initials(user.name)}
              </span>
              <div className="min-w-0 flex-1">
                <b className="block truncate text-[13px] font-medium text-ink">
                  {user.name}
                </b>
                <span className="block truncate text-[11.5px] text-ink-faint">
                  {AUTH_ENABLED ? 'Free' : 'Open access'}
                </span>
              </div>
            </div>
          )}
          {AUTH_ENABLED && (
            <button
              type="button"
              onClick={signOut}
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-ink-dim transition-colors hover:bg-surface-soft hover:text-ink [&_svg]:size-4"
            >
              <SignOutIcon />
              Sign out
            </button>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex flex-wrap items-center justify-between gap-4 border-b border-line bg-surface px-6 py-3.5">
          <div className="min-w-0">
            <h1 className="text-[17px] leading-tight font-semibold tracking-[-0.02em] text-ink">
              {title}
            </h1>
            {subtitle && (
              <p className="mt-0.5 text-[12.5px] text-ink-dim">{subtitle}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <NotificationBell />
            {actions && <div className="flex items-center gap-2">{actions}</div>}
          </div>
        </header>

        {/* Mobile nav — the sidebar is hidden under md. */}
        <nav className="flex gap-1 border-b border-line px-3 py-2 md:hidden">
          {NAV_MAIN.map((item) => {
            const Icon = item.icon
            const active = route === item.to
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  'flex flex-1 items-center justify-center gap-2 rounded-full py-1.5 text-[13px] [&_svg]:size-4',
                  active
                    ? 'bg-surface-sunk font-medium text-ink'
                    : 'text-ink-mid',
                )}
              >
                <Icon />
                {item.label}
              </Link>
            )
          })}
        </nav>

        <div className="min-w-0 flex-1 px-6 py-6">{children}</div>
      </div>
    </div>
  )
}
