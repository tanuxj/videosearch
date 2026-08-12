/**
 * Ambient background layers — the "depth" half of the redesign.
 *
 * All of these are Aceternity patterns retuned for a light UI: the originals
 * assume a near-black canvas where a saturated glow reads as premium. On white
 * the same colours turn muddy, so here the washes stay in the 6–14% opacity
 * range and lean on the existing `--accent` / `--accent-2` tokens instead of
 * neon. Every layer is decorative and `aria-hidden`.
 */

import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

/**
 * Soft aurora wash. Two large blurred blobs drifting behind the content.
 *
 * Uses CSS animation rather than motion/react: it runs forever and never
 * interacts, so keeping it off the JS main thread is free performance. The
 * blobs sit in an `overflow-hidden` frame so the blur never triggers page
 * scrollbars.
 */
export function AuroraBackground({
  className,
  children,
}: {
  className?: string
  children?: ReactNode
}) {
  return (
    <div className={cn('relative isolate', className)}>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
      >
        <div className="animate-aurora absolute -top-[28rem] left-1/2 h-[52rem] w-[64rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle_at_center,color-mix(in_oklab,var(--accent)_14%,transparent),transparent_68%)] blur-3xl" />
        <div
          className="animate-aurora absolute -top-64 right-[-14rem] h-[40rem] w-[40rem] rounded-full bg-[radial-gradient(circle_at_center,color-mix(in_oklab,var(--accent-2)_12%,transparent),transparent_70%)] blur-3xl"
          style={{ animationDelay: '-7s' }}
        />
      </div>
      {children}
    </div>
  )
}

/**
 * Faint graph-paper grid that fades out towards the edges.
 *
 * The mask is what keeps it from looking like a spreadsheet — without the
 * radial fade a full-bleed grid fights the content for attention.
 */
export function GridPattern({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'pointer-events-none absolute inset-0 -z-10',
        '[background-image:linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)]',
        '[background-size:64px_64px]',
        '[mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_60%,transparent_100%)]',
        className,
      )}
    />
  )
}

/** Dotted texture, same masking trick as {@link GridPattern}. */
export function DotPattern({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'pointer-events-none absolute inset-0 -z-10',
        '[background-image:radial-gradient(var(--border-strong)_1px,transparent_1px)]',
        '[background-size:22px_22px]',
        '[mask-image:radial-gradient(ellipse_70%_60%_at_50%_40%,#000_50%,transparent_100%)]',
        className,
      )}
    />
  )
}

/**
 * A single hero spotlight — one wide, very soft conic wash from the top-left.
 *
 * Deliberately static. The animated version in the original library sweeps on
 * mount, which on a light background reads as a rendering glitch rather than an
 * effect.
 */
export function Spotlight({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'pointer-events-none absolute -top-40 left-1/2 -z-10 h-[40rem] w-[72rem] -translate-x-1/2',
        'bg-[conic-gradient(from_180deg_at_50%_50%,color-mix(in_oklab,var(--accent)_10%,transparent)_0deg,transparent_120deg,color-mix(in_oklab,var(--accent-2)_10%,transparent)_240deg,transparent_360deg)]',
        'opacity-70 blur-3xl',
        className,
      )}
    />
  )
}
