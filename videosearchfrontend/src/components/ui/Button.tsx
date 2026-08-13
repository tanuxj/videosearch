/**
 * Buttons and link-buttons.
 *
 * Flat by design: one solid brand fill, one bordered variant, one quiet variant.
 * No gradients, no inset highlights, no glow — the only depth cue is a hairline
 * border, and hover just shifts the background a step.
 *
 * These intentionally do not reuse the legacy `.btn` classes — mixing the two on
 * one element means fighting `index.css` over padding and font.
 */

import type { ComponentPropsWithoutRef, ElementType, ReactNode } from 'react'
import { cn } from '../../lib/cn'

// Fully-rounded pills at every size, matching the reference UI.
const SIZES = {
  sm: 'h-8 px-3 text-[13px] gap-1.5',
  md: 'h-9 px-4 text-[13.5px] gap-2',
  lg: 'h-11 px-5 text-[14.5px] gap-2',
} as const

const VARIANTS = {
  /** The one primary action in a view. */
  primary: 'text-white bg-brand hover:bg-brand-hover',
  /** Bordered and white — the default for everything else. */
  secondary: 'text-ink bg-panel border border-line-strong hover:bg-surface-soft',
  /** No chrome until hovered. */
  ghost: 'text-ink-mid hover:bg-surface-sunk hover:text-ink',
  /** Destructive. */
  danger: 'text-white bg-danger hover:brightness-95',
} as const

type ButtonBaseProps = {
  variant?: keyof typeof VARIANTS
  size?: keyof typeof SIZES
  className?: string
  children: ReactNode
}

const BASE = cn(
  'relative inline-flex shrink-0 items-center justify-center rounded-full',
  'font-medium whitespace-nowrap',
  'transition-colors duration-150',
  'disabled:pointer-events-none disabled:opacity-50',
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

/** Square icon-only control (toolbar buttons, overflow menus, close). */
export function IconButton({
  label,
  children,
  className,
  ...rest
}: {
  label: string
  children: ReactNode
  className?: string
} & Omit<ComponentPropsWithoutRef<'button'>, 'aria-label'>) {
  return (
    <button
      type="button"
      aria-label={label}
      className={cn(
        'grid size-8 shrink-0 place-items-center rounded-full text-ink-dim',
        'transition-colors hover:bg-surface-sunk hover:text-ink',
        'disabled:pointer-events-none disabled:opacity-40',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand',
        '[&_svg]:size-4',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}
