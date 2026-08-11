import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from '../lib/router'
import { authErrorMessage, useAuth } from '../lib/auth'
import { AuthLayout, Field } from '../components/AuthLayout'
import { LockIcon, MailIcon } from '../components/Icons'

export default function Login() {
  const { signIn } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const next: Record<string, string> = {}
    if (!/^\S+@\S+\.\S+$/.test(email)) next.email = 'Enter a valid email address.'
    if (!password) next.password = 'Enter your password.'
    setErrors(next)
    setFormError('')
    if (Object.keys(next).length > 0) return

    setBusy(true)
    try {
      await signIn(email, password)
      navigate('/dashboard', true)
    } catch (error) {
      setFormError(authErrorMessage(error, 'Could not sign you in.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      <div className="auth-head">
        <h1>Welcome back</h1>
        <p>Sign in to search your indexed videos.</p>
      </div>

      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        {formError && (
          <p className="alert" role="alert">
            {formError}
          </p>
        )}

        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          placeholder="you@company.com"
          autoComplete="email"
          icon={<MailIcon />}
          error={errors.email}
        />

        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          placeholder="Your password"
          autoComplete="current-password"
          icon={<LockIcon />}
          error={errors.password}
        />

        <div className="auth-meta">
          <label>
            <input type="checkbox" defaultChecked />
            Keep me signed in
          </label>
          <a href="#reset">Forgot password?</a>
        </div>

        <button
          type="submit"
          className="btn btn-primary btn-lg btn-block"
          disabled={busy}
        >
          {busy && <span className="spinner" />}
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>

      <p className="auth-alt">
        New here? <Link to="/signup">Create an account</Link>
      </p>
    </AuthLayout>
  )
}
