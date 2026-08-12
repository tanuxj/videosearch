/**
 * Motion primitives: scroll reveal, marquee, shimmer skeleton, animated tabs.
 */

import { type ReactNode } from 'react'
import { motion } from 'motion/react'
import { cn } from '../../lib/cn'

/**
 * Fades and lifts its children the first time they scroll into view.
 *
 * `once: true` matters — re-animating on every scroll past is the single
 * fastest way to make a page feel cheap. The margin fires it slightly before
 * the element is fully visible so the motion finishes as the reader arrives.
 */
export function Reveal({
  children,
  className,
  delay = 0,
  y = 14,
}: {
  children: ReactNode
  className?: string
  delay?: number
  y?: number
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  )
}

/**
 * Seamless horizontal marquee.
 *
 * The track renders `children` twice and translates by -50%, so the second copy
 * lands exactly where the first started — that is what makes the loop
 * invisible. Pauses on hover so a reader can actually look at an item.
 */
export function Marquee({
  children,
  className,
  reverse = false,
}: {
  children: ReactNode
  className?: string
  reverse?: boolean
}) {
  return (
    <div
      className={cn(
        'group relative overflow-hidden',
        '[mask-image:linear-gradient(to_right,transparent,#000_12%,#000_88%,transparent)]',
        className,
      )}
    >
      <div
        className="animate-marquee flex w-max gap-3 group-hover:[animation-play-state:paused]"
        style={reverse ? { animationDirection: 'reverse' } : undefined}
      >
        {children}
        <span aria-hidden="true" className="flex gap-3">
          {children}
        </span>
      </div>
    </div>
  )
}

/** Loading placeholder with a light sweep across it. */
export function Shimmer({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        'animate-shimmer rounded-lg bg-surface-sunk',
        'bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.85),transparent)]',
        'bg-[length:220%_100%] bg-no-repeat',
        className,
      )}
    />
  )
}

/**
 * Pill tabs where the active background slides between items.
 *
 * The slide comes from a shared `layoutId` — motion animates the single
 * highlight element between positions instead of cross-fading two backgrounds.
 */
export function AnimatedTabs<T extends string>({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
  className?: string
}) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1 rounded-xl border border-line bg-surface-soft p-1',
        className,
      )}
    >
      {tabs.map((tab) => {
        const active = tab.value === value
        return (
          <button
            key={tab.value}
            type="button"
            onClick={() => onChange(tab.value)}
            aria-pressed={active}
            className={cn(
              'relative rounded-[9px] px-3 py-1.5 text-[13px] font-medium transition-colors',
              active ? 'text-ink' : 'text-ink-dim hover:text-ink',
            )}
          >
            {active && (
              <motion.span
                layoutId="tab-pill"
                className="absolute inset-0 -z-10 rounded-[9px] border border-line bg-panel shadow-[0_1px_2px_rgba(16,19,26,0.06)]"
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              />
            )}
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}
