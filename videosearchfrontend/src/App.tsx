import { useEffect } from 'react'
import { AuthProvider, useAuth } from './lib/auth'
import { Link, useNavigate, useRoute } from './lib/router'
import { MarketingShell } from './components/Shell'
import { AuroraBackground, GridPattern } from './components/ui/Backgrounds'
import { GlowButton } from './components/ui/Button'
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
      <AuroraBackground className="px-6 py-24 text-center">
        <GridPattern />
        <Eyebrow>
          <span className="font-mono font-semibold">404</span>
          Page not found
        </Eyebrow>
        <h1 className="mx-auto mt-6 max-w-[20ch] text-[clamp(2rem,5vw,3.2rem)] leading-[1.05] font-bold tracking-[-0.035em] text-ink">
          This page doesn’t exist
        </h1>
        <p className="mx-auto mt-4 max-w-[52ch] text-[16px] leading-relaxed text-ink-mid">
          The link may be out of date. Head back and pick up where you left off.
        </p>
        <div className="mt-8 flex justify-center">
          <GlowButton as={Link} to="/">
            Back to home
          </GlowButton>
        </div>
      </AuroraBackground>
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
