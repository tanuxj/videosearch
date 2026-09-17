import { useEffect } from 'react'
import { AuthProvider, useAuth } from './lib/auth'
import { AUTH_ENABLED } from './lib/http'
import { SINGLE_PAGE, SINGLE_PAGE_ROUTE } from './lib/features'
import { Link, useNavigate, useRoute } from './lib/router'
import { MarketingShell } from './components/Shell'
import { ButtonLink } from './components/ui/Button'
import { Eyebrow } from './components/ui/Text'
import Home from './pages/Home'
import Pricing from './pages/Pricing'
import Login from './pages/Login'
import Signup from './pages/Signup'
import Dashboard from './pages/Dashboard'
import Clips from './pages/Clips'
import Search from './pages/Search'
import Record from './pages/Record'
import Recordings from './pages/Recordings'
import Share from './pages/Share'
import Workspaces from './pages/Workspaces'
import Terms from './pages/Terms'
import Privacy from './pages/Privacy'

const PROTECTED = new Set([
  '/dashboard',
  '/upload',
  '/search',
  '/clips',
  '/record',
  '/recordings',
  '/workspaces',
])
const AUTH_ONLY = new Set(['/login', '/signup'])
/**
 * Routes single-page mode folds away. They stay in the bundle and still work
 * the moment `VITE_SINGLE_PAGE` is off — they just redirect to the one page
 * while it is on, so a stale link or bookmark lands somewhere useful instead
 * of on a screen with no way back.
 */
const FOLDED_AWAY = new Set([
  '/dashboard',
  '/clips',
  '/record',
  '/recordings',
  '/workspaces',
])

function NotFound() {
  return (
    <MarketingShell>
      <section className="px-6 py-24 text-center">
        <Eyebrow>
          <span className="font-medium">404</span>
          Page not found
        </Eyebrow>
        <h1 className="mx-auto mt-6 max-w-[20ch] text-[clamp(1.9rem,4.5vw,2.9rem)] leading-[1.08] font-semibold tracking-[-0.03em] text-ink">
          This page doesn’t exist
        </h1>
        <p className="mx-auto mt-4 max-w-[52ch] text-[15.5px] leading-relaxed text-ink-mid">
          The link may be out of date. Head back and pick up where you left off.
        </p>
        <div className="mt-7 flex justify-center">
          <ButtonLink as={Link} to="/" size="lg">
            Back to home
          </ButtonLink>
        </div>
      </section>
    </MarketingShell>
  )
}

function Routes() {
  const route = useRoute()
  const navigate = useNavigate()
  const { user, ready } = useAuth()

  // Accounts off: the landing page and the two sign-in routes collapse onto
  // the single upload-and-search page. `PROTECTED` never fires because there
  // is always a user. Single-page mode folds the remaining workspace pages in
  // the same way, so `/` is the search page under either switch.
  const redirectToOnePage =
    (!AUTH_ENABLED && (route === '/' || AUTH_ONLY.has(route))) ||
    (SINGLE_PAGE && (route === '/' || FOLDED_AWAY.has(route)))

  useEffect(() => {
    if (!ready) return
    if (redirectToOnePage) {
      navigate(SINGLE_PAGE_ROUTE, true)
      return
    }
    if (!user && PROTECTED.has(route)) navigate('/login', true)
    if (user && AUTH_ENABLED && AUTH_ONLY.has(route)) navigate('/dashboard', true)
    // Upload is a dialog now — keep the old link working.
    if (user && route === '/upload') navigate('/search?upload=1', true)
    // History was renamed to Clips — keep the old link working. In
    // single-page mode Clips is folded away, so go straight to the one page
    // rather than bouncing through a route that only redirects again.
    if (user && route === '/history') {
      navigate(SINGLE_PAGE ? SINGLE_PAGE_ROUTE : '/clips', true)
    }
  }, [ready, user, route, navigate, redirectToOnePage])

  // Hold the first paint until the stored session is known — otherwise
  // protected pages flash before the redirect lands.
  if (!ready) return null
  if (redirectToOnePage) return null
  if (!user && PROTECTED.has(route)) return null
  if (user && AUTH_ENABLED && AUTH_ONLY.has(route)) return null

  // Share pages are deliberately public — no session, no app shell.
  if (route.startsWith('/share/')) {
    return <Share token={route.slice('/share/'.length)} />
  }

  switch (route) {
    case '/':
      return <Home />
    case '/pricing':
      return <Pricing />
    case '/login':
      return <Login />
    case '/signup':
      return <Signup />
    // Both redirected above when accounts are disabled.
    case '/dashboard':
      return <Dashboard />
    case '/search':
      return <Search />
    case '/clips':
      return <Clips />
    case '/record':
      return <Record />
    case '/recordings':
      return <Recordings />
    case '/workspaces':
      return <Workspaces />
    case '/terms':
      return <Terms />
    case '/privacy':
      return <Privacy />
    case '/upload':
    case '/history':
      return null // redirected above
    default:
      return <NotFound />
  }
}

export default function App() {
  return (
    <AuthProvider>
      <Routes />
    </AuthProvider>
  )
}
