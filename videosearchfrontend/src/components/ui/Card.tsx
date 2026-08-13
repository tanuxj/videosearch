/**
 * Flat surfaces.
 *
 * A card here is a white panel with a hairline border and nothing else — no
 * cursor spotlight, no lift on hover, no gradient edge. Where a card is
 * interactive, hover tints the background one step instead of moving it.
 */

import type { CSSProperties, ReactNode } from 'react'
import { cn } from '../../lib/cn'

export function Card({
  className,
  children,
  as: Tag = 'div',
  interactive = false,
}: {
  className?: string
  children: ReactNode
  as?: 'div' | 'article' | 'li' | 'label' | 'section'
  /** Adds a hover background. Use on cards that are themselves clickable. */
  interactive?: boolean
}) {
  return (
    <Tag
      className={cn(
        'rounded-xl border border-line bg-panel',
        interactive && 'transition-colors hover:bg-surface-soft',
        className,
      )}
    >
      {children}
    </Tag>
  )
}

/**
 * Bento grid: 3 columns on desktop, stacking on mobile. Kept because the
 * asymmetric layout carries the feature section without needing decoration.
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
        'grid grid-cols-1 gap-3 md:grid-cols-3 md:auto-rows-[12rem]',
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
    <Card
      as="article"
      className={cn('flex flex-col p-5', SPANS[span] ?? SPANS['1x1'], className)}
    >
      <div style={style} className="flex h-full flex-col">
        {icon && (
          <span className="mb-3 inline-flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-wash text-brand [&_svg]:size-4">
            {icon}
          </span>
        )}
        <h3 className="text-[14.5px] leading-snug font-semibold text-ink">
          {title}
        </h3>
        {body && (
          <p className="mt-1.5 text-[13px] leading-relaxed text-ink-dim">
            {body}
          </p>
        )}
        {children}
      </div>
    </Card>
  )
}
