import { useEffect, useState, type ReactNode } from 'react'
import { Link, useRoute } from '../lib/router'
import { initials, useAuth } from '../lib/auth'
import { cn } from '../lib/cn'
import { ButtonLink } from './ui/Button'
import { GridIcon, SearchIcon, SignOutIcon } from './Icons'
import { LogoMark, Wordmark } from './Logo'

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

const MARKETING_LINKS = [
  { href: '#how', label: 'How it works' },
  { href: '#features', label: 'Features' },
  { href: '#pricing', label: 'Pricing' },
]

export function MarketingShell({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  // Only frost the bar once the page has moved — a blurred bar over the very
  // top of the hero just looks like a rendering seam.
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
          'sticky top-0 z-50 transition-[background-color,border-color,backdrop-filter] duration-300',
          scrolled
            ? 'border-b border-line bg-panel/75 backdrop-blur-xl'
            : 'border-b border-transparent bg-transparent',
        )}
      >
        <div className="mx-auto flex h-16 w-full max-w-[1120px] items-center gap-6 px-6">
          <Brand />
          <nav className="ml-2 hidden items-center gap-1 md:flex">
            {MARKETING_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="rounded-lg px-3 py-2 text-[14px] font-medium text-ink-mid transition-colors hover:bg-surface-sunk hover:text-ink"
              >
                {link.label}
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {user ? (
              <ButtonLink as={Link} to="/search" size="sm">
                Open workspace
              </ButtonLink>
            ) : (
              <>
                <ButtonLink as={Link} to="/login" variant="ghost" size="sm">
                  Sign in
                </ButtonLink>
                <ButtonLink as={Link} to="/signup" size="sm">
                  Get started
                </ButtonLink>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-line bg-surface-soft">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col items-center justify-between gap-4 px-6 py-8 sm:flex-row">
          <div className="flex items-center gap-2.5">
            <LogoMark className="size-5 opacity-70" />
            <span className="text-[13px] text-ink-dim">
              © {new Date().getFullYear()} {APP_NAME}
            </span>
          </div>
          <nav className="flex items-center gap-5">
            {['Privacy', 'Terms', 'Docs'].map((label) => (
              <a
                key={label}
                href={`#${label.toLowerCase()}`}
                className="text-[13px] text-ink-dim transition-colors hover:text-brand"
              >
                {label}
              </a>
            ))}
          </nav>
        </div>
      </footer>
    </div>
  )
}

/* ── Authenticated app ──────────────────────────────────── */

// Upload isn't a page any more — it's a dialog you can open from anywhere,
// so the workspace is just "find a scene" and "the library you search over".
const NAV = [
  { to: '/search', label: 'Find a scene', icon: SearchIcon },
  { to: '/dashboard', label: 'Library', icon: GridIcon },
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
    <div className="flex min-h-screen bg-surface-soft">
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col border-r border-line bg-panel md:flex">
        <div className="flex h-16 items-center px-5">
          <Brand to="/dashboard" />
        </div>

        <p className="px-5 pt-3 pb-2 text-[11px] font-semibold tracking-[0.09em] text-ink-faint uppercase">
          Workspace
        </p>
        <nav className="flex flex-col gap-0.5 px-3">
          {NAV.map((item) => {
            const Icon = item.icon
            const active = route === item.to
            return (
              <Link
                key={item.to}
                to={item.to}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'relative flex items-center gap-2.5 rounded-[10px] px-3 py-2 text-[14px] font-medium transition-colors',
                  '[&_svg]:size-[18px]',
                  active
                    ? 'bg-brand-wash text-brand'
                    : 'text-ink-mid hover:bg-surface-sunk hover:text-ink',
                )}
              >
                {/* Active rail — reads as "you are here" without a heavy fill. */}
                {active && (
                  <span className="absolute top-1/2 left-0 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-brand" />
                )}
                <Icon />
                <span>{item.label}</span>
              </Link>
            )
          })}
        </nav>

        <div className="mt-auto border-t border-line p-3">
          {user && (
            <div className="mb-2 flex items-center gap-2.5 rounded-xl bg-surface-soft p-2.5">
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-[linear-gradient(135deg,var(--accent),var(--accent-2))] text-[12.5px] font-semibold text-white">
                {initials(user.name)}
              </span>
              <div className="min-w-0">
                <b className="block truncate text-[13px] font-semibold text-ink">
                  {user.name}
                </b>
                <span className="block truncate text-[11.5px] text-ink-faint">
                  {user.email}
                </span>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={signOut}
            className="flex w-full items-center gap-2 rounded-[10px] px-3 py-2 text-[13px] font-medium text-ink-dim transition-colors hover:bg-danger-wash hover:text-danger [&_svg]:size-4"
          >
            <SignOutIcon />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex flex-wrap items-end justify-between gap-4 border-b border-line bg-panel/80 px-6 py-4 backdrop-blur-xl md:px-8">
          <div className="min-w-0">
            <h1 className="text-[21px] leading-tight font-bold tracking-[-0.025em] text-ink">
              {title}
            </h1>
            {subtitle && (
              <p className="mt-1 text-[13.5px] text-ink-dim">{subtitle}</p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>

        {/* Mobile nav — the sidebar is hidden under md. */}
        <nav className="flex gap-1 border-b border-line bg-panel px-4 py-2 md:hidden">
          {NAV.map((item) => {
            const Icon = item.icon
            const active = route === item.to
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  'flex flex-1 items-center justify-center gap-2 rounded-[10px] py-2 text-[13px] font-medium [&_svg]:size-4',
                  active ? 'bg-brand-wash text-brand' : 'text-ink-mid',
                )}
              >
                <Icon />
                {item.label}
              </Link>
            )
          })}
        </nav>

        <div className="min-w-0 flex-1 px-6 py-6 md:px-8">{children}</div>
      </div>
    </div>
  )
}
