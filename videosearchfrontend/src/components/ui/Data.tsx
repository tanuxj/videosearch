/**
 * Dashboard furniture: stat tiles, panels, status chips, empty states.
 *
 * The stat tiles follow the data-viz house rules:
 *
 * * Value in the same sans as the rest of the UI, semibold, with the font's
 *   *proportional* figures — `tabular-nums` widens every digit to a zero, which
 *   reads loose at display sizes and is meant for columns that must align.
 * * Values arrive pre-compacted (`12.9K`, `4.2 GB`) from `lib/format`.
 * * Labels are sentence case with no trailing colon.
 * * Text uses ink tokens only — the accent is carried by the small icon, never
 *   by the number, so nothing depends on hue to be readable.
 * * No tooltip: a tile with no plot has nothing to reveal on hover.
 */

import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'
import { Card } from './Card'

export function StatTile({
  label,
  value,
  meta,
  icon,
}: {
  label: string
  value: string
  meta?: string
  icon?: ReactNode
}) {
  return (
    <Card className="p-4">
      <span className="flex items-center gap-2 text-[12.5px] font-medium text-ink-dim [&_svg]:size-4 [&_svg]:text-brand">
        {icon}
        {label}
      </span>
      <b className="mt-2.5 block text-[24px] leading-none font-semibold tracking-[-0.025em] text-ink">
        {value}
      </b>
      {meta && (
        <span className="mt-1.5 block text-[12px] text-ink-faint">{meta}</span>
      )}
    </Card>
  )
}

export function StatRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>
}

/** Bordered section with a heading row. */
export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section
      className={cn(
        'overflow-hidden rounded-xl border border-line bg-panel',
        className,
      )}
    >
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <div>
            {title && (
              <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
            )}
            {subtitle && (
              <p className="mt-0.5 text-[12.5px] text-ink-dim">{subtitle}</p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

/**
 * Status chip. Always renders a label beside the dot — state is never carried by
 * colour alone, which is what keeps it readable under CVD and in grayscale.
 */
const TONES = {
  ok: 'bg-ok-wash text-ok',
  warn: 'bg-warn-wash text-warn',
  danger: 'bg-danger-wash text-danger',
  brand: 'bg-brand-wash text-brand',
  neutral: 'bg-surface-sunk text-ink-dim',
} as const

export function Chip({
  tone = 'neutral',
  children,
  title,
  pulse = false,
  icon,
}: {
  tone?: keyof typeof TONES
  children: ReactNode
  title?: string
  pulse?: boolean
  /** Replaces the status dot — used for metadata pills like "Private". */
  icon?: ReactNode
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1',
        'text-[11.5px] font-medium whitespace-nowrap',
        '[&_svg]:size-3',
        TONES[tone],
      )}
    >
      {icon ?? (
        <i
          aria-hidden="true"
          className={cn(
            'size-1.5 rounded-full bg-current',
            pulse && 'animate-pulse',
          )}
        />
      )}
      {children}
    </span>
  )
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode
  title: string
  body?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center px-6 py-16 text-center">
      {icon && (
        <span className="mb-4 grid size-12 place-items-center rounded-full bg-brand-wash text-brand [&_svg]:size-5">
          {icon}
        </span>
      )}
      <h3 className="text-[16px] font-semibold text-ink">{title}</h3>
      {body && (
        <p className="mt-2 max-w-[46ch] text-[13.5px] leading-relaxed text-ink-dim">
          {body}
        </p>
      )}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}
