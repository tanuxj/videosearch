/**
 * Card surfaces: cursor spotlight, animated border, and the bento grid.
 *
 * Light-mode adaptations of the Aceternity card patterns. The originals paint a
 * bright radial glow on dark card stock; inverted onto white that would blow
 * out, so the spotlight here is a ~7% tint of the brand colour plus a slightly
 * brighter border — closer to a sheet of paper catching light than to a lamp.
 */

import {
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
} from 'react'
import { cn } from '../../lib/cn'

/**
 * Card whose surface highlights around the cursor.
 *
 * Pointer position is written to CSS custom properties rather than React state
 * for the gradient itself — re-rendering on every mousemove would be wasteful.
 * A boolean `hovered` state still drives the fade so the glow does not pop in.
 */
export function SpotlightCard({
  className,
  children,
  as: Tag = 'div',
}: {
  className?: string
  children: ReactNode
  as?: 'div' | 'article' | 'li' | 'label'
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [hovered, setHovered] = useState(false)

  function handleMove(event: MouseEvent<HTMLElement>) {
    const node = ref.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    node.style.setProperty('--spot-x', `${event.clientX - rect.left}px`)
    node.style.setProperty('--spot-y', `${event.clientY - rect.top}px`)
  }

  return (
    <Tag
      // The ref type is narrowed to HTMLDivElement for convenience; every
      // allowed tag is still an HTMLElement, which is all `handleMove` needs.
      ref={ref as never}
      onMouseMove={handleMove}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={cn(
        'group relative overflow-hidden rounded-2xl border border-line bg-panel',
        'transition-[transform,box-shadow,border-color] duration-300 ease-out',
        'hover:-translate-y-0.5 hover:border-brand-line hover:shadow-[0_18px_40px_-18px_rgba(16,19,26,0.18)]',
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 transition-opacity duration-300"
        style={{
          opacity: hovered ? 1 : 0,
          background:
            'radial-gradient(320px circle at var(--spot-x, 50%) var(--spot-y, 0px), color-mix(in oklab, var(--accent) 7%, transparent), transparent 72%)',
        }}
      />
      <div className="relative">{children}</div>
    </Tag>
  )
}

/**
 * Card with a gradient hairline that traces its edge.
 *
 * Built as a padded gradient parent wrapping an opaque child, so the "border"
 * is really the 1px of parent showing through. That keeps the corners perfectly
 * round, which a `border-image` gradient cannot do.
 */
export function GlowBorderCard({
  className,
  innerClassName,
  children,
}: {
  className?: string
  innerClassName?: string
  children: ReactNode
}) {
  return (
    <div
      className={cn(
        'relative rounded-2xl p-px',
        'bg-[linear-gradient(130deg,var(--accent-line),transparent_38%,transparent_62%,color-mix(in_oklab,var(--accent-2)_35%,transparent))]',
        className,
      )}
    >
      <div className={cn('rounded-[calc(1rem-1px)] bg-panel', innerClassName)}>
        {children}
      </div>
    </div>
  )
}

/**
 * Bento grid: a 3-column asymmetric layout on desktop, stacking on mobile.
 *
 * Children control their own span via `BentoCard`'s `span` prop, which is what
 * makes the layout read as composed rather than as a uniform card wall.
 */
export function BentoGrid({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 gap-4 md:grid-cols-3 md:auto-rows-[13rem]',
        className,
      )}
    >
      {children}
    </div>
  )
}

const SPANS: Record<string, string> = {
  '1x1': 'md:col-span-1 md:row-span-1',
  '2x1': 'md:col-span-2 md:row-span-1',
  '1x2': 'md:col-span-1 md:row-span-2',
  '2x2': 'md:col-span-2 md:row-span-2',
  '3x1': 'md:col-span-3 md:row-span-1',
}

export function BentoCard({
  title,
  body,
  icon,
  span = '1x1',
  className,
  children,
  style,
}: {
  title: string
  body?: string
  icon?: ReactNode
  span?: keyof typeof SPANS | string
  className?: string
  children?: ReactNode
  style?: CSSProperties
}) {
  return (
    <SpotlightCard
      as="article"
      className={cn('flex flex-col p-5', SPANS[span] ?? SPANS['1x1'], className)}
    >
      <div style={style} className="flex h-full flex-col">
        {icon && (
          <span className="mb-3 inline-flex size-9 shrink-0 items-center justify-center rounded-xl border border-brand-line bg-brand-wash text-brand [&_svg]:size-[18px]">
            {icon}
          </span>
        )}
        <h3 className="text-[15px] leading-snug font-semibold tracking-[-0.01em] text-ink">
          {title}
        </h3>
        {body && (
          <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-dim">
            {body}
          </p>
        )}
        {children}
      </div>
    </SpotlightCard>
  )
}
