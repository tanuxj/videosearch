import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from '../lib/router'
import { authErrorMessage, useAuth } from '../lib/auth'
import {
  Alert,
  AuthHead,
  AuthLayout,
  Field,
  Spinner,
} from '../components/AuthLayout'
import { Button } from '../components/ui/Button'
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
      <AuthHead title="Welcome back">
        Sign in to search your indexed videos.
      </AuthHead>

      <form className="flex flex-col gap-4" onSubmit={handleSubmit} noValidate>
        {formError && <Alert>{formError}</Alert>}

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

        <div className="flex items-center justify-between text-[13px]">
          <label className="flex cursor-pointer items-center gap-2 text-ink-mid">
            <input
              type="checkbox"
              defaultChecked
              className="size-4 accent-[var(--accent)]"
            />
            Keep me signed in
          </label>
          <a
            href="#reset"
            className="font-medium text-brand transition-opacity hover:opacity-75"
          >
            Forgot password?
          </a>
        </div>

        <Button type="submit" size="lg" disabled={busy} className="mt-1 w-full">
          {busy && <Spinner />}
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>

      <p className="mt-6 text-center text-[13.5px] text-ink-dim">
        New here?{' '}
        <Link
          to="/signup"
          className="font-medium text-brand transition-opacity hover:opacity-75"
        >
          Create an account
        </Link>
      </p>
    </AuthLayout>
  )
}
