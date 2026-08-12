import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import { Brand } from './Shell'
import { cn } from '../lib/cn'
import { AuroraBackground, DotPattern } from './ui/Backgrounds'
import { GlowBorderCard } from './ui/Card'

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

/**
 * Labelled input with an optional leading icon and a password reveal toggle.
 *
 * The focus ring lives on the wrapper, not the `input` — the icon and toggle sit
 * inside the same bordered box, so highlighting the input alone would draw a
 * ring through the middle of the control.
 */
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
    <div>
      <label
        htmlFor={id}
        className="mb-1.5 block text-[13px] font-medium text-ink-mid"
      >
        {label}
      </label>
      <div
        className={cn(
          'flex items-center gap-2.5 rounded-xl border bg-panel px-3.5',
          'transition-[border-color,box-shadow] duration-150',
          'focus-within:border-brand focus-within:shadow-[0_0_0_4px_color-mix(in_oklab,var(--accent)_13%,transparent)]',
          '[&>svg]:size-[17px] [&>svg]:shrink-0 [&>svg]:text-ink-faint',
          error ? 'border-danger' : 'border-line-strong',
        )}
      >
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
          className="h-11 min-w-0 flex-1 bg-transparent text-[14.5px] text-ink outline-none placeholder:text-ink-faint"
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setRevealed((open) => !open)}
            aria-label={revealed ? 'Hide password' : 'Show password'}
            className="shrink-0 rounded-md px-1.5 py-1 text-[12px] font-medium text-ink-dim transition-colors hover:text-brand"
          >
            {revealed ? 'Hide' : 'Show'}
          </button>
        )}
      </div>
      {error ? (
        <p className="mt-1.5 text-[12.5px] text-danger" id={`${id}-msg`}>
          {error}
        </p>
      ) : hint ? (
        <p className="mt-1.5 text-[12.5px] text-ink-faint" id={`${id}-msg`}>
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
    <div className="grid min-h-screen lg:grid-cols-[1fr_minmax(420px,46%)]">
      {/* Form side */}
      <div className="flex flex-col bg-surface px-6 py-8 sm:px-10">
        <Brand />
        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center py-10">
          {children}
        </div>
      </div>

      {/* Showcase side — hidden on narrow screens where it would just push the
          form below the fold. */}
      <AuroraBackground className="hidden flex-col justify-center border-l border-line bg-surface-soft px-10 py-12 lg:flex">
        <DotPattern className="opacity-70" />

        <GlowBorderCard innerClassName="p-7">
          <blockquote className="text-[19px] leading-relaxed font-medium tracking-[-0.015em] text-ink">
            “We stopped scrubbing through raw footage entirely. You describe the
            shot you remember, and it’s just there.”
          </blockquote>
          <footer className="mt-6 flex items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-[linear-gradient(135deg,var(--accent),var(--accent-2))] text-[13px] font-semibold text-white">
              RM
            </span>
            <div className="text-[13px] leading-snug">
              <b className="font-semibold text-ink">Rae Mercado</b>
              <span className="text-ink-dim"> · Post-production lead</span>
              <div className="text-ink-faint">Northlight Studios</div>
            </div>
          </footer>
        </GlowBorderCard>

        <div className="mt-6 grid grid-cols-3 gap-3">
          {STATS.map((stat) => (
            <div
              key={stat.label}
              className="rounded-xl border border-line bg-panel/70 p-4 text-center backdrop-blur"
            >
              <b className="block font-mono text-[19px] font-semibold tracking-[-0.02em] text-ink">
                {stat.value}
              </b>
              <span className="mt-0.5 block text-[11.5px] text-ink-faint">
                {stat.label}
              </span>
            </div>
          ))}
        </div>
      </AuroraBackground>
    </div>
  )
}

/* ── Shared auth page furniture ─────────────────────────── */

export function AuthHead({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <div className="mb-7">
      <h1 className="text-[27px] leading-tight font-bold tracking-[-0.03em] text-ink">
        {title}
      </h1>
      <p className="mt-2 text-[14.5px] text-ink-dim">{children}</p>
    </div>
  )
}

/** Inline form-level error banner. */
export function Alert({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="rounded-xl border border-danger/25 bg-danger-wash px-3.5 py-2.5 text-[13px] text-danger"
    >
      {children}
    </p>
  )
}

/** Spinner for busy buttons. */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-block size-4 shrink-0 animate-spin rounded-full',
        'border-2 border-current/30 border-t-current',
        className,
      )}
    />
  )
}
