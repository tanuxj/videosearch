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
      navigate('/search?upload=1', true)
    } catch (error) {
      setFormError(authErrorMessage(error, 'Could not create the account.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      <AuthHead title="Create your account">
        Upload a video and search it by description in minutes.
      </AuthHead>

      <form className="flex flex-col gap-4" onSubmit={handleSubmit} noValidate>
        {formError && <Alert>{formError}</Alert>}

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

        <Button type="submit" size="lg" disabled={busy} className="mt-1 w-full">
          {busy && <Spinner />}
          {busy ? 'Creating account…' : 'Create account'}
        </Button>

        <p className="text-center text-[12px] leading-relaxed text-ink-faint">
          By continuing you agree to our{' '}
          <Link
            to="/terms"
            className="text-ink-dim underline underline-offset-2"
          >
            Terms of Service
          </Link>{' '}
          and{' '}
          <Link
            to="/privacy"
            className="text-ink-dim underline underline-offset-2"
          >
            Privacy Policy
          </Link>
          .
        </p>
      </form>

      <p className="mt-6 text-center text-[13.5px] text-ink-dim">
        Already have an account?{' '}
        <Link
          to="/login"
          className="font-medium text-brand transition-opacity hover:opacity-75"
        >
          Sign in
        </Link>
      </p>
    </AuthLayout>
  )
}
