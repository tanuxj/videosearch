/**
 * Inline icons — stroke icons inherit `stroke` from CSS, the solid play glyph
 * inherits `fill`. Sizing is handled by the parent rule in index.css.
 */

import type { ReactNode } from 'react'

type Props = { className?: string }

function Stroke({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {children}
    </svg>
  )
}

export const PlayIcon = ({ className }: Props) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" className={className}>
    <path d="M8 5.14v13.72L19 12 8 5.14z" />
  </svg>
)

export const SearchIcon = () => (
  <Stroke>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.5-3.5" />
  </Stroke>
)

export const SparkIcon = () => (
  <Stroke>
    <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />
    <path d="M18.5 16.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z" />
  </Stroke>
)

export const UploadIcon = () => (
  <Stroke>
    <path d="M12 16V4" />
    <path d="M7.5 8.5L12 4l4.5 4.5" />
    <path d="M4 16v2.5A1.5 1.5 0 005.5 20h13a1.5 1.5 0 001.5-1.5V16" />
  </Stroke>
)

export const FilmIcon = () => (
  <Stroke>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <path d="M8 4v16M16 4v16M3 12h18M3 8h5M16 8h5M3 16h5M16 16h5" />
  </Stroke>
)

export const GridIcon = () => (
  <Stroke>
    <rect x="3.5" y="3.5" width="7" height="7" rx="2" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="2" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="2" />
    <rect x="13.5" y="13.5" width="7" height="7" rx="2" />
  </Stroke>
)

export const ClockIcon = () => (
  <Stroke>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 1.8" />
  </Stroke>
)

export const BoltIcon = () => (
  <Stroke>
    <path d="M13 3L5.5 13.5H11l-1 7.5 7.5-10.5H12l1-7.5z" />
  </Stroke>
)

export const LayersIcon = () => (
  <Stroke>
    <path d="M12 3.5l8.5 4.5-8.5 4.5L3.5 8 12 3.5z" />
    <path d="M3.5 12.5L12 17l8.5-4.5" />
    <path d="M3.5 16.8L12 21.3l8.5-4.5" />
  </Stroke>
)

export const ShieldIcon = () => (
  <Stroke>
    <path d="M12 3.2l7 2.6v5.4c0 4.3-2.9 8.2-7 9.6-4.1-1.4-7-5.3-7-9.6V5.8l7-2.6z" />
    <path d="M9 12l2 2 4-4" />
  </Stroke>
)

export const MailIcon = () => (
  <Stroke>
    <rect x="3" y="5" width="18" height="14" rx="2.5" />
    <path d="M3.8 7l7.3 5.2a1.5 1.5 0 001.8 0L20.2 7" />
  </Stroke>
)

export const LockIcon = () => (
  <Stroke>
    <rect x="4.5" y="10" width="15" height="10.5" rx="2.5" />
    <path d="M8 10V7.5a4 4 0 018 0V10" />
  </Stroke>
)

export const UserIcon = () => (
  <Stroke>
    <circle cx="12" cy="8.5" r="3.8" />
    <path d="M4.8 20a7.2 7.2 0 0114.4 0" />
  </Stroke>
)

export const CheckIcon = () => (
  <Stroke>
    <path d="M5 12.5l4.5 4.5L19 7" />
  </Stroke>
)

export const SignOutIcon = () => (
  <Stroke>
    <path d="M14 6.5V5a2 2 0 00-2-2H6a2 2 0 00-2 2v14a2 2 0 002 2h6a2 2 0 002-2v-1.5" />
    <path d="M10.5 12H21M17.5 8.5L21 12l-3.5 3.5" />
  </Stroke>
)

export const CloseIcon = () => (
  <Stroke>
    <path d="M6 6l12 12M18 6L6 18" />
  </Stroke>
)

export const ChevronIcon = () => (
  <Stroke>
    <path d="M7 10l5 5 5-5" />
  </Stroke>
)

export const ArrowLeftIcon = () => (
  <Stroke>
    <path d="M20 12H4M9.5 6.5L4 12l5.5 5.5" />
  </Stroke>
)

export const ArrowRightIcon = () => (
  <Stroke>
    <path d="M4 12h16M14.5 6.5L20 12l-5.5 5.5" />
  </Stroke>
)

export const TrashIcon = () => (
  <Stroke>
    <path d="M4.5 7h15M9.5 7V5.5A1.5 1.5 0 0111 4h2a1.5 1.5 0 011.5 1.5V7" />
    <path d="M6.5 7l.8 12a2 2 0 002 1.9h5.4a2 2 0 002-1.9l.8-12" />
  </Stroke>
)
