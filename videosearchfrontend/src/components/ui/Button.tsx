/**
 * Buttons and link-buttons for the redesigned surfaces.
 *
 * These intentionally do not reuse the legacy `.btn` classes — mixing the two
 * on one element means fighting `index.css` over padding and font. New markup
 * uses these; anything still on `.btn` keeps working untouched.
 */

import type { ComponentPropsWithoutRef, ElementType, ReactNode } from 'react'
import { cn } from '../../lib/cn'

const SIZES = {
  sm: 'h-9 px-3.5 text-[13px] rounded-[10px] gap-1.5',
  md: 'h-10 px-4 text-[14px] rounded-[11px] gap-2',
  lg: 'h-12 px-6 text-[15px] rounded-[13px] gap-2',
} as const

const VARIANTS = {
  /** Brand fill with a lit top edge — the one primary action per view. */
  primary: cn(
    'text-white bg-[linear-gradient(180deg,color-mix(in_oklab,var(--accent)_92%,white),var(--accent))]',
    'shadow-[0_1px_0_rgba(255,255,255,0.28)_inset,0_10px_24px_-12px_color-mix(in_oklab,var(--accent)_65%,transparent)]',
    'hover:brightness-[1.06] active:brightness-[0.97]',
  ),
  /** Bordered, panel-coloured. */
  secondary: cn(
    'text-ink bg-panel border border-line-strong',
    'shadow-[0_1px_2px_rgba(16,19,26,0.05)]',
    'hover:border-brand-line hover:bg-surface-soft',
  ),
  /** No chrome until hovered. */
  ghost: 'text-ink-mid hover:text-ink hover:bg-surface-sunk',
  /** Destructive. */
  danger: 'text-white bg-danger hover:brightness-[1.06]',
} as const

type ButtonBaseProps = {
  variant?: keyof typeof VARIANTS
  size?: keyof typeof SIZES
  className?: string
  children: ReactNode
}

const BASE = cn(
  'relative inline-flex items-center justify-center font-medium whitespace-nowrap',
  'transition-[filter,background-color,border-color,color,transform] duration-150',
  'active:translate-y-px',
  'disabled:pointer-events-none disabled:opacity-55',
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand',
)

export function Button({
  variant = 'primary',
  size = 'md',
  className,
  children,
  ...rest
}: ButtonBaseProps & ComponentPropsWithoutRef<'button'>) {
  return (
    <button
      className={cn(BASE, SIZES[size], VARIANTS[variant], className)}
      {...rest}
    >
      {children}
    </button>
  )
}

/**
 * Same visuals as {@link Button} but renders whatever element you pass — used
 * for the router's `Link`, which needs `to` rather than `href`.
 */
export function ButtonLink<T extends ElementType>({
  as,
  variant = 'primary',
  size = 'md',
  className,
  children,
  ...rest
}: { as: T } & ButtonBaseProps &
  Omit<ComponentPropsWithoutRef<T>, 'className' | 'children'>) {
  const Tag = as as ElementType
  return (
    <Tag
      className={cn(BASE, SIZES[size], VARIANTS[variant], className)}
      {...rest}
    >
      {children}
    </Tag>
  )
}

/**
 * CTA with a gradient hairline that pulses.
 *
 * The glow is a blurred copy of the button sitting behind it, which is why the
 * wrapper needs `isolate` — otherwise the blur bleeds over neighbours.
 */
export function GlowButton({
  className,
  children,
  as,
  ...rest
}: { as?: ElementType } & ButtonBaseProps &
  Record<string, unknown>) {
  const Tag = (as ?? 'button') as ElementType
  return (
    <span className="relative isolate inline-flex">
      <span
        aria-hidden="true"
        className="animate-glow-line absolute -inset-1 -z-10 rounded-[18px] bg-[linear-gradient(100deg,var(--accent),var(--accent-2))] opacity-45 blur-lg"
      />
      <Tag
        className={cn(BASE, SIZES.lg, VARIANTS.primary, className)}
        {...rest}
      >
        {children}
      </Tag>
    </span>
  )
}
