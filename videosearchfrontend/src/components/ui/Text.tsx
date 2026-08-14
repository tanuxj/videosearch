/**
 * Small text furniture. The gradient-fill and word-reveal headline treatments
 * are gone — headings are plain ink now.
 */

import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

/** Quiet pill used above a heading. */
export function Eyebrow({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 rounded-full bg-brand-wash',
        'px-3 py-1 text-[12.5px] font-medium text-brand',
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Section heading + supporting line, centred. */
export function SectionHead({
  title,
  children,
  className,
}: {
  title: string
  children?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('mx-auto max-w-[54ch] text-center', className)}>
      <h2 className="text-[clamp(1.5rem,3vw,2.1rem)] leading-tight font-semibold tracking-[-0.025em] text-ink">
        {title}
      </h2>
      {children && (
        <p className="mt-3 text-[15.5px] leading-relaxed text-ink-dim">
          {children}
        </p>
      )}
    </div>
  )
}
