import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import { Brand } from './Shell'

/* ── Text field ─────────────────────────────────────────── */

type FieldProps = {
  label: string
  type?: 'text' | 'email' | 'password'
  value: string
  onChange: (value: string) => void
  placeholder?: string
  autoComplete?: string
  icon?: ReactNode
  error?: string
  hint?: string
}

export function Field({
  label,
  type = 'text',
  value,
  onChange,
  placeholder,
  autoComplete,
  icon,
  error,
  hint,
}: FieldProps) {
  const id = useId()
  const [revealed, setRevealed] = useState(false)
  const isPassword = type === 'password'
  const inputType = isPassword && revealed ? 'text' : type

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="field-input">
        {icon}
        <input
          id={id}
          type={inputType}
          value={value}
          placeholder={placeholder}
          autoComplete={autoComplete}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error || hint ? `${id}-msg` : undefined}
          onChange={(event) => onChange(event.target.value)}
        />
        {isPassword && (
          <button
            type="button"
            className="field-toggle"
            onClick={() => setRevealed((open) => !open)}
            aria-label={revealed ? 'Hide password' : 'Show password'}
          >
            {revealed ? 'Hide' : 'Show'}
          </button>
        )}
      </div>
      {error ? (
        <p className="field-error" id={`${id}-msg`}>
          {error}
        </p>
      ) : hint ? (
        <p className="field-hint" id={`${id}-msg`}>
          {hint}
        </p>
      ) : null}
    </div>
  )
}

/* ── Split auth layout ──────────────────────────────────── */

const STATS = [
  { value: '1.2s', label: 'Median search' },
  { value: '60/min', label: 'Frames indexed' },
  { value: '94%', label: 'Top-1 hit rate' },
]

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth">
      <div className="auth-form-side">
        <Brand />
        <div className="auth-form-wrap">{children}</div>
      </div>

      <aside className="auth-aside">
        <div className="auth-quote">
          <blockquote>
            “We stopped scrubbing through raw footage entirely. You describe the
            shot you remember, and it’s just there.”
          </blockquote>
          <footer>
            <span className="avatar">RM</span>
            <div>
              <b>Rae Mercado</b> · Post-production lead
              <div>Northlight Studios</div>
            </div>
          </footer>
        </div>

        <div className="auth-stats">
          {STATS.map((stat) => (
            <div key={stat.label} className="auth-stat">
              <b>{stat.value}</b>
              <span>{stat.label}</span>
            </div>
          ))}
        </div>
      </aside>
    </div>
  )
}
