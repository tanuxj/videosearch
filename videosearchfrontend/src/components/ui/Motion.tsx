/**
 * What's left of the motion layer.
 *
 * Scroll reveals, word-by-word headlines and the marquee are gone. The only
 * movement that survives is movement that orients the reader: a dialog
 * entering (see Modal), a dropdown opening (see VideoSelect), and the tab
 * highlight sliding between positions so you can see which one you left.
 */

import { motion } from 'motion/react'
import { cn } from '../../lib/cn'

/** Loading placeholder with a light sweep across it. */
export function Shimmer({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        'animate-shimmer rounded-lg bg-surface-sunk',
        'bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.9),transparent)]',
        'bg-[length:220%_100%] bg-no-repeat',
        className,
      )}
    />
  )
}

/**
 * Pill tabs where the active background slides between items.
 *
 * The slide comes from a shared `layoutId` — motion animates one highlight
 * element between positions rather than cross-fading two backgrounds.
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
    <div className={cn('inline-flex items-center gap-1', className)}>
      {tabs.map((tab) => {
        const active = tab.value === value
        return (
          <button
            key={tab.value}
            type="button"
            onClick={() => onChange(tab.value)}
            aria-pressed={active}
            className={cn(
              'relative rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors',
              active ? 'text-ink' : 'text-ink-dim hover:text-ink',
            )}
          >
            {active && (
              <motion.span
                layoutId="tab-pill"
                className="absolute inset-0 -z-10 rounded-full border border-line bg-panel"
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
