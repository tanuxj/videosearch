import { useEffect, useState, type ReactNode } from 'react'
import { Link, useRoute } from '../lib/router'
import { initials, useAuth } from '../lib/auth'
import { cn } from '../lib/cn'
import { ButtonLink } from './ui/Button'
import { GridIcon, SearchIcon, SignOutIcon, UploadIcon } from './Icons'
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
              <a
                key={link.href}
                href={link.href}
                className="rounded-full px-3 py-1.5 text-[13.5px] text-ink-mid transition-colors hover:bg-surface-sunk hover:text-ink"
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

      <footer className="border-t border-line">
        <div className="mx-auto flex w-full max-w-[1080px] flex-col items-center justify-between gap-3 px-6 py-7 sm:flex-row">
          <span className="text-[12.5px] text-ink-faint">
            © {new Date().getFullYear()} {APP_NAME}
          </span>
          <nav className="flex items-center gap-5">
            {['Privacy', 'Terms', 'Docs'].map((label) => (
              <a
                key={label}
                href={`#${label.toLowerCase()}`}
                className="text-[12.5px] text-ink-faint transition-colors hover:text-ink"
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

const NAV_MAIN = [
  { to: '/search', label: 'Search', icon: SearchIcon },
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

export function AppShell({ title, subtitle, actions, children }: AppShellProps) {
  const route = useRoute()
  const { user, signOut } = useAuth()

  return (
    <div className="flex min-h-screen bg-surface">
      <aside className="sticky top-0 hidden h-screen w-[240px] shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="flex h-16 items-center px-4">
          <Brand to="/dashboard" />
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
                  Free
                </span>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={signOut}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-ink-dim transition-colors hover:bg-surface-soft hover:text-ink [&_svg]:size-4"
          >
            <SignOutIcon />
            Sign out
          </button>
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
          {actions && <div className="flex items-center gap-2">{actions}</div>}
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
