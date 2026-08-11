import { useEffect } from 'react'
import { AuthProvider, useAuth } from './lib/auth'
import { Link, useNavigate, useRoute } from './lib/router'
import { MarketingShell } from './components/Shell'
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
      <section className="wrap hero">
        <span className="eyebrow">
          <b>404</b> Page not found
        </span>
        <h1>This page doesn’t exist</h1>
        <p className="hero-sub">
          The link may be out of date. Head back and pick up where you left off.
        </p>
        <div className="hero-cta">
          <Link to="/" className="btn btn-primary btn-lg">
            Back to home
          </Link>
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
