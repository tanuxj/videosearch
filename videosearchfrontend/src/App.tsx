import { useEffect } from 'react'
import { AuthProvider, useAuth } from './lib/auth'
import { Link, useNavigate, useRoute } from './lib/router'
import { MarketingShell } from './components/Shell'
import { ButtonLink } from './components/ui/Button'
import { Eyebrow } from './components/ui/Text'
import Home from './pages/Home'
import Login from './pages/Login'
import Signup from './pages/Signup'
import Dashboard from './pages/Dashboard'
import Search from './pages/Search'

const PROTECTED = new Set(['/dashboard', '/upload', '/search'])
const AUTH_ONLY = new Set(['/login', '/signup'])

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

  useEffect(() => {
    if (!ready) return
    if (!user && PROTECTED.has(route)) navigate('/login', true)
    if (user && AUTH_ONLY.has(route)) navigate('/dashboard', true)
    // Upload is a dialog now — keep the old link working.
    if (user && route === '/upload') navigate('/search?upload=1', true)
  }, [ready, user, route, navigate])

  // Hold the first paint until the stored session is known — otherwise
  // protected pages flash before the redirect lands.
  if (!ready) return null
  if (!user && PROTECTED.has(route)) return null
  if (user && AUTH_ONLY.has(route)) return null

  switch (route) {
    case '/':
      return <Home />
    case '/login':
      return <Login />
    case '/signup':
      return <Signup />
    case '/dashboard':
      return <Dashboard />
    case '/search':
      return <Search />
    case '/upload':
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
