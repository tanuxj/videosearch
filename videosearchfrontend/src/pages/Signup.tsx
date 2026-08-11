import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from '../lib/router'
import { useAuth } from '../lib/auth'
import { AuthLayout, Field } from '../components/AuthLayout'
import { LockIcon, MailIcon, UserIcon } from '../components/Icons'

export default function Signup() {
  const { signUp } = useAuth()
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const next: Record<string, string> = {}
    if (name.trim().length < 2) next.name = 'Tell us what to call you.'
    if (!/^\S+@\S+\.\S+$/.test(email)) next.email = 'Enter a valid email address.'
    if (password.length < 8) next.password = 'Use at least 8 characters.'
    setErrors(next)
    setFormError('')
    if (Object.keys(next).length > 0) return

    setBusy(true)
    try {
      await signUp(name, email, password)
      navigate('/upload', true)
    } catch (error) {
      setFormError(
        error instanceof Error ? error.message : 'Could not create the account.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      <div className="auth-head">
        <h1>Create your account</h1>
        <p>Upload a video and search it by description in minutes.</p>
      </div>

      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        {formError && (
          <p className="alert" role="alert">
            {formError}
          </p>
        )}

        <Field
          label="Full name"
          value={name}
          onChange={setName}
          placeholder="Alex Rivera"
          autoComplete="name"
          icon={<UserIcon />}
          error={errors.name}
        />

        <Field
          label="Work email"
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
          placeholder="At least 8 characters"
          autoComplete="new-password"
          icon={<LockIcon />}
          error={errors.password}
          hint="Use 8 or more characters."
        />

        <button
          type="submit"
          className="btn btn-primary btn-lg btn-block"
          disabled={busy}
        >
          {busy && <span className="spinner" />}
          {busy ? 'Creating account…' : 'Create account'}
        </button>

        <p className="auth-legal">
          By continuing you agree to our <a href="#terms">Terms of Service</a>{' '}
          and <a href="#privacy">Privacy Policy</a>.
        </p>
      </form>

      <p className="auth-alt">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthLayout>
  )
}
